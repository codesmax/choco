import asyncio
import os
import time
import pygame
from threading import Lock
from loguru import logger
from chocopi.config import USE_DISPLAY, IS_PI, IMAGES_PATH, FONTS_PATH

class DisplayManager:
    """Manages visual display with sprite animations and transcript"""

    def __init__(self, config):
        self.config = config.display

        # Computed dimensions based on config
        self.screen_width = self.config.width
        self.screen_height = self.config.height
        self.pane_width = self.screen_width // 2  # Split screen in half
        self.graphics_width = self.pane_width
        self.transcript_width = self.pane_width
        self.gradient_width = 200  # Gradient spans from 1/4 to 1/2 of screen
        self.gradient_start = self.pane_width - self.gradient_width
        self.transcript_margin = 10

        # Thread safety (lock still needed for pygame operations)
        self.lock = Lock()
        self.is_running = False

        # State
        self.is_active = False  # False = sleeping (dimmed), True = awake
        self.is_speaking = False
        self.transcripts = []  # List of (speaker, text) tuples

        # Animation
        self.animation_frame = 0
        self.sleeping_animation_frame = 0
        self.ping_pong_frames = [0, 1, 2, 3, 2, 1]  # Ping-pong pattern
        self.last_frame_time = 0

        # Pygame surfaces (initialized in run loop)
        self.screen = None
        self.idle_sprite = None
        self.speaking_frames = []
        self.sleeping_frames = []
        self.font = None
        self.gradient = None

    def _init_pygame(self):
        """Initialize pygame"""
        try:
            # Initialize required subsystems (no audio - conflicts with AudioManager)
            pygame.display.init()
            pygame.font.init()

            if driver := pygame.display.get_driver():
                logger.info("🖥️  Display driver loaded: {}", driver)
            else:
                logger.error("⚠️  No display driver available, disabling visual output")
                return False

            # Set window icon before creating the display surface
            icon_path = IMAGES_PATH / 'chocopi-icon.png'
            if icon_path.exists():
                pygame.display.set_icon(pygame.image.load(str(icon_path)))

            # On Pi: true fullscreen. On desktop: resizable window
            flags = pygame.FULLSCREEN if IS_PI else pygame.RESIZABLE
            self.screen = pygame.display.set_mode(
                (self.screen_width, self.screen_height),
                flags,
            )
            pygame.display.set_caption("ChocoPi")
            pygame.mouse.set_visible(not IS_PI)

            self._load_sprites()
            self.font = self._load_font()
            self._create_gradient()

            logger.info("🖥️  Display initialized @ {}x{} resolution", self.config.width, self.config.height)
            return True

        except Exception as e:
            logger.error("❌ Failed to initialize display: {}", e)
            return False

    def _load_font(self):
        """Load font with multilingual support"""
        font_size = self.config.font_size
        bundled_font = os.path.join(FONTS_PATH, self.config.font)
        if os.path.exists(bundled_font):
            logger.info("📝 Using bundled font: {}", bundled_font)
            return pygame.font.Font(bundled_font, font_size)

        # Fallback to system fonts with multilingual support
        system_fonts = ['notosanscjk', 'notosans', 'arial', 'helvetica', 'freesans']
        logger.info("📝 Using system font fallback: {}", system_fonts)
        return pygame.font.SysFont(system_fonts, font_size)

    def _load_sprites(self):
        """Load idle and speaking sprites"""
        # Idle
        idle_path = os.path.join(IMAGES_PATH, self.config.sprites.idle)
        idle_sprite = pygame.image.load(idle_path)
        if idle_sprite.get_size() == (self.pane_width, self.screen_height):
            self.idle_sprite = idle_sprite
        else:
            self.idle_sprite = pygame.transform.smoothscale(idle_sprite, (self.pane_width, self.screen_height))

        # Speaking sprite sheet (horizontal layout: 4 frames)
        speaking_path = os.path.join(IMAGES_PATH, self.config.sprites.speaking)
        spritesheet = pygame.image.load(speaking_path)

        # Split into 4 frames scaled to pane size
        frame_width = spritesheet.get_width() // 4
        frame_height = spritesheet.get_height()

        for i in range(4):
            frame = spritesheet.subsurface((i * frame_width, 0, frame_width, frame_height))
            scaled_frame = pygame.transform.smoothscale(frame, (self.pane_width, self.screen_height))
            self.speaking_frames.append(scaled_frame)

        # Sleeping sprite sheet (horizontal layout: 4 frames)
        sleeping_path = os.path.join(IMAGES_PATH, self.config.sprites.sleeping)
        sleeping_sheet = pygame.image.load(sleeping_path)

        # Split into 4 frames scaled to full screen
        frame_width = sleeping_sheet.get_width() // 4
        frame_height = sleeping_sheet.get_height()

        for i in range(4):
            frame = sleeping_sheet.subsurface((i * frame_width, 0, frame_width, frame_height))
            scaled_frame = pygame.transform.smoothscale(frame, (self.screen_width, self.screen_height))
            self.sleeping_frames.append(scaled_frame)

    def _create_gradient(self):
        """Create gradient surface for smooth transition between panes"""
        self.gradient = pygame.Surface((self.gradient_width, self.screen_height), pygame.SRCALPHA)
        graphics_bg = pygame.Color(self.config.colors.graphics_bg)
        transcript_bg = pygame.Color(self.config.colors.transcript_bg)

        # Create vertical gradient from graphics_bg to transcript_bg
        for x in range(self.gradient_width):
            ratio = x / self.gradient_width
            r = int(graphics_bg.r + (transcript_bg.r - graphics_bg.r) * ratio)
            g = int(graphics_bg.g + (transcript_bg.g - graphics_bg.g) * ratio)
            b = int(graphics_bg.b + (transcript_bg.b - graphics_bg.b) * ratio)

            pygame.draw.line(self.gradient, (r, g, b), (x, 0), (x, self.screen_height))

    def _render_frame(self):
        """Render a single frame"""
        with self.lock:
            is_active = self.is_active
            is_speaking = self.is_speaking
            animation_frame = self.animation_frame
            sleeping_frame = self.sleeping_animation_frame

        if not is_active:
            # Sleeping state - clear screen and show sleeping animation
            self.screen.fill(pygame.Color("#141414"))
            self.screen.blit(self.sleeping_frames[sleeping_frame], (0, 0))
            pygame.display.flip()
            return

        # Active state
        graphics_bg = pygame.Color(self.config.colors.graphics_bg)
        transcript_bg = pygame.Color(self.config.colors.transcript_bg)

        # Clear graphics pane (left)
        self.screen.fill(graphics_bg, (0, 0, self.pane_width, self.screen_height))

        # Draw gradient below animation sprite
        self.screen.blit(self.gradient, (self.gradient_start, 0))

        # Clear transcript pane (right)
        self.screen.fill(transcript_bg, (self.pane_width, 0, self.transcript_width, self.screen_height))

        if is_speaking:
            # Animate through ping-pong frames
            frame_idx = self.ping_pong_frames[animation_frame]
            self.screen.blit(self.speaking_frames[frame_idx], (0, 0))
        else:
            self.screen.blit(self.idle_sprite, (0, 0))

        # Render transcripts
        self._render_transcripts()

        pygame.display.flip()

    def _render_transcripts(self):
        """Render transcript text in right pane with scrolling"""
        with self.lock:
            if not self.transcripts:
                return
            transcripts_copy = list(self.transcripts)

        active_color = pygame.Color(self.config.colors.active_text)
        choco_color = pygame.Color(self.config.colors.choco_text)
        user_color = pygame.Color(self.config.colors.user_text)

        # Newest messages at bottom
        y = self.screen_height - self.transcript_margin
        line_height = self.config.font_size + self.config.line_spacing
        for idx, (speaker, wrapped_lines) in enumerate(reversed(transcripts_copy)):
            # Most recent transcript uses active color
            if idx == 0:
                color = active_color
            elif speaker == "user":
                color = user_color
            else:
                color = choco_color

            # Render lines from bottom up
            for line in reversed(wrapped_lines):
                text_surface = self.font.render(line, True, color)

                # Check if space is available at top
                if y - text_surface.get_height() < 0:
                    return

                # Draw text
                self.screen.blit(text_surface, (self.pane_width + self.transcript_margin, y - text_surface.get_height()))
                y -= line_height

    def _wrap_text(self, text, max_width):
        """Wrap text to fit within max_width pixels"""
        words = text.split(' ')
        lines = []
        current_line = []

        for word in words:
            # Test to account for variability in line width
            test_line = ' '.join(current_line + [word])
            test_surface = self.font.render(test_line, True, (255, 255, 255))

            if test_surface.get_width() <= max_width:
                current_line.append(word)
            else:
                # If current line has content, save it
                if current_line:
                    lines.append(' '.join(current_line))
                    current_line = []

                # If single word is too wide, break it character-by-character
                if self.font.render(word, True, (255, 255, 255)).get_width() > max_width:
                    char_line = ""
                    for char in word:
                        test_char = char_line + char
                        if self.font.render(test_char, True, (255, 255, 255)).get_width() <= max_width:
                            char_line += char
                        else:
                            if char_line:
                                lines.append(char_line)
                            char_line = char
                    if char_line:
                        current_line = [char_line]
                else:
                    current_line = [word]

        if current_line:
            lines.append(' '.join(current_line))

        return lines

    def _update_animation(self):
        """Update animation frame based on FPS"""
        current_time = time.time()

        # Use different FPS for sleeping vs speaking
        if not self.is_active:
            frame_duration = 1.0 / self.config.frame_rates.sleeping
        else:
            frame_duration = 1.0 / self.config.frame_rates.speaking

        if current_time - self.last_frame_time >= frame_duration:
            with self.lock:
                if not self.is_active:
                    # Advance sleeping frame (sequential loop)
                    self.sleeping_animation_frame = (self.sleeping_animation_frame + 1) % 4
                elif self.is_speaking:
                    # Advance ping-pong frame
                    self.animation_frame = (self.animation_frame + 1) % len(self.ping_pong_frames)

            self.last_frame_time = current_time

    async def run(self):
        """Main display loop (runs as async task)"""
        logger.debug("🎬 Display task starting...")

        # Initialize pygame (always in main thread with asyncio)
        if not self._init_pygame():
            logger.error("❌ Display initialization failed")
            return

        self.is_running = True
        frame_count = 0

        logger.debug("🔄 Display loop starting...")
        try:
            while self.is_running:
                # Handle pygame events
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        self.is_running = False

                self._update_animation()
                self._render_frame()

                # Variable FPS: refresh rate when awake, sleeping animation rate when sleeping
                with self.lock:
                    fps = self.config.frame_rates.refresh if self.is_active else self.config.frame_rates.sleeping
                await asyncio.sleep(1.0 / fps)

                frame_count += 1
                if frame_count == 1:
                    logger.debug("✅ First frame rendered")
                elif frame_count % (fps * 10) == 0:  # Every 10 seconds
                    logger.debug("🎬 Display running... {} frames rendered", frame_count)
        finally:
            logger.debug("🛑 Display loop ending")
            pygame.quit()

    def set_active(self, active):
        """Set display active state (True = awake, False = sleeping)"""
        with self.lock:
            self.is_active = active
            if not active:
                # Clear transcripts when going to sleep
                self.transcripts = []
                self.is_speaking = False
                self.sleeping_animation_frame = 0

    def set_speaking(self, speaking):
        """Update speaking state (thread-safe)"""
        with self.lock:
            was_speaking = self.is_speaking
            self.is_speaking = speaking
            if speaking and not was_speaking:
                self.animation_frame = 0
                self.last_frame_time = time.time()
                logger.debug("🎬 Animation started")

    def add_transcript(self, speaker, text):
        """Add a transcript line (thread-safe)"""
        with self.lock:
            # Replace newlines with spaces for proper rendering
            filtered_text = text.replace('\n', ' ').replace('\r', ' ')

            # Prefix based on speaker
            prefix = "You: " if speaker == "user" else "Choco: "

            # Add word wrapped text
            max_width = self.transcript_width - (self.transcript_margin * 2)
            wrapped_lines = self._wrap_text(prefix + filtered_text, max_width)
            self.transcripts.append((speaker, wrapped_lines))

            # Limit to last 10 transcripts
            if len(self.transcripts) > 10:
                self.transcripts.pop(0)


def create_display_manager(config):
    """Factory function to create display manager if enabled"""
    if not USE_DISPLAY:
        logger.info("🖥️  Display disabled, skipping display manager initialization")
        return None

    try:
        return DisplayManager(config)
    except Exception as e:
        logger.error("⚠️  Failed to initialize display manager: {}", e)
        return None
