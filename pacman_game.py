"""
吃豆子游戏 (Pac-Man) - 使用 Pygame
控制：方向键移动，R 重新开始，Q 退出
吃掉所有豆子即可获胜，被幽灵碰到则失去生命。
"""

import pygame
import sys
import random
from collections import deque

# 常量
CELL = 20
ROWS = 11
COLS = 21
WIDTH = COLS * CELL
HEIGHT = ROWS * CELL + 40
FPS = 10

# 颜色
BLACK = (0, 0, 0)
BLUE = (0, 0, 180)
WHITE = (255, 255, 255)
YELLOW = (255, 255, 0)
RED = (255, 0, 0)
PINK = (255, 180, 255)
CYAN = (0, 255, 255)
GRAY = (30, 30, 70)
WALL_COLOR = (20, 20, 180)

# 迷宫：1=墙, 0=通道(有豆子), 2=通道(无豆子), 3=大力丸
MAZE = [
    [1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],
    [3,0,0,0,0,0,0,0,0,0,1,0,0,0,0,0,0,0,0,0,3],
    [1,0,1,1,0,1,1,0,1,0,1,0,1,0,1,1,0,1,1,0,1],
    [1,0,0,0,0,0,0,0,1,0,0,0,1,0,0,0,0,0,0,0,1],
    [1,0,1,1,0,1,0,1,1,1,1,1,1,1,0,1,0,1,1,0,1],
    [1,0,0,0,0,1,0,0,0,2,2,2,0,0,0,1,0,0,0,0,1],
    [1,0,1,0,1,1,1,1,0,1,1,1,1,0,1,1,1,1,0,1,1],
    [1,0,0,0,1,0,0,0,0,1,2,2,1,0,0,0,0,1,0,0,1],
    [1,0,1,1,1,0,1,1,1,1,2,2,1,1,1,1,0,1,1,1,1],
    [3,0,0,0,0,0,0,1,0,0,0,0,0,0,1,0,0,0,0,0,3],
    [1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],
]

# 方向
UP = (0, -1)
DOWN = (0, 1)
LEFT = (-1, 0)
RIGHT = (1, 0)
DIRS = [UP, DOWN, LEFT, RIGHT]


class Pacman:
    """吃豆人"""
    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.direction = RIGHT
        self.next_dir = RIGHT
        self.mouth_open = True
        self.anim_timer = 0

    def set_direction(self, d):
        self.next_dir = d

    def move(self, maze):
        # 尝试转向
        nx = self.x + self.next_dir[0]
        ny = self.y + self.next_dir[1]
        if 0 <= ny < ROWS and 0 <= nx < COLS and maze[ny][nx] != 1:
            self.direction = self.next_dir
            self.x, self.y = nx, ny
        else:
            # 继续当前方向
            nx = self.x + self.direction[0]
            ny = self.y + self.direction[1]
            if 0 <= ny < ROWS and 0 <= nx < COLS and maze[ny][nx] != 1:
                self.x, self.y = nx, ny

        self.anim_timer += 1
        if self.anim_timer >= 3:
            self.mouth_open = not self.mouth_open
            self.anim_timer = 0

    def draw(self, screen):
        cx = self.x * CELL + CELL // 2
        cy = self.y * CELL + CELL // 2
        r = CELL // 2 - 2

        # 嘴巴角度
        if self.mouth_open:
            if self.direction == RIGHT:
                start_a, end_a = 0.5, 5.8
            elif self.direction == LEFT:
                start_a, end_a = 3.64, 2.64
            elif self.direction == UP:
                start_a, end_a = 4.71, 1.5
            else:
                start_a, end_a = 1.57, 4.7
        else:
            start_a, end_a = 0, 6.28

        # 画身体
        import math
        points = [(cx, cy)]
        for a in range(int(start_a * 100), int(end_a * 100) + 1):
            rad = a / 100.0
            # 确保在0-2pi范围内调整
            while rad < start_a:
                rad += 6.28
            while rad > end_a + 0.01:
                rad -= 6.28
            if start_a <= rad <= end_a or end_a < start_a:
                px = cx + r * math.cos(rad)
                py = cy - r * math.sin(rad)
                points.append((px, py))

        if len(points) >= 3:
            pygame.draw.polygon(screen, YELLOW, points)
        else:
            pygame.draw.circle(screen, YELLOW, (cx, cy), r)


class Ghost:
    """幽灵"""
    def __init__(self, x, y, color):
        self.x = x
        self.y = y
        self.color = color
        self.direction = random.choice(DIRS)
        self.frightened = False
        self.fright_timer = 0

    def move(self, maze, target_x, target_y):
        if self.frightened:
            self.fright_timer -= 1
            if self.fright_timer <= 0:
                self.frightened = False

        # 找可走方向（不允许掉头）
        possible = []
        for d in DIRS:
            back = (-self.direction[0], -self.direction[1])
            if d == back:
                continue
            nx = self.x + d[0]
            ny = self.y + d[1]
            if 0 <= ny < ROWS and 0 <= nx < COLS and maze[ny][nx] != 1:
                possible.append(d)

        if not possible:
            # 死路，掉头
            for d in DIRS:
                nx = self.x + d[0]
                ny = self.y + d[1]
                if 0 <= ny < ROWS and 0 <= nx < COLS and maze[ny][nx] != 1:
                    possible.append(d)

        if self.frightened:
            # 受惊模式：随机移动
            self.direction = random.choice(possible)
        else:
            # 追踪模式：选离目标最近的方向
            best_dir = possible[0]
            best_dist = 9999
            for d in possible:
                nx = self.x + d[0]
                ny = self.y + d[1]
                dist = abs(nx - target_x) + abs(ny - target_y)
                if dist < best_dist:
                    best_dist = dist
                    best_dir = d
            self.direction = best_dir

        self.x += self.direction[0]
        self.y += self.direction[1]

    def draw(self, screen):
        cx = self.x * CELL + CELL // 2
        cy = self.y * CELL + CELL // 2
        r = CELL // 2 - 2
        color = BLUE if self.frightened else self.color

        # 身体（圆角矩形效果用圆代替）
        pygame.draw.circle(screen, color, (cx, cy - 2), r)
        # 底部波浪
        base_y = cy + r - 2
        wave_w = r // 2
        for i in range(-r, r + 1, wave_w):
            wx = cx + i
            if i + wave_w > r:
                ww = r - i
            else:
                ww = wave_w
            if ww > 0:
                pygame.draw.circle(screen, color, (wx + ww // 2, base_y), ww // 2)

        # 眼睛
        eye_r = 4
        eye_y = cy - 4
        if self.frightened:
            # 受惊眼睛是 X 形
            eye_size = 3
            for ex in [cx - 5, cx + 5]:
                pygame.draw.line(screen, WHITE, (ex - eye_size, eye_y - eye_size),
                                 (ex + eye_size, eye_y + eye_size), 1)
                pygame.draw.line(screen, WHITE, (ex + eye_size, eye_y - eye_size),
                                 (ex - eye_size, eye_y + eye_size), 1)
        else:
            pygame.draw.circle(screen, WHITE, (cx - 5, eye_y), eye_r)
            pygame.draw.circle(screen, WHITE, (cx + 5, eye_y), eye_r)
            # 瞳孔
            pupil_r = 2
            pupil_off_x = self.direction[0] * 2
            pupil_off_y = self.direction[1] * 2
            pygame.draw.circle(screen, BLACK, (cx - 5 + pupil_off_x, eye_y + pupil_off_y), pupil_r)
            pygame.draw.circle(screen, BLACK, (cx + 5 + pupil_off_x, eye_y + pupil_off_y), pupil_r)


def init_dots(maze):
    """初始化豆子位置"""
    dots = []
    power_dots = []
    for y in range(ROWS):
        for x in range(COLS):
            if maze[y][x] == 0:
                dots.append((x, y))
            elif maze[y][x] == 3:
                dots.append((x, y))
                power_dots.append((x, y))
    return dots, power_dots


def draw_maze(screen, maze, dots, power_dots):
    """绘制迷宫和豆子"""
    for y in range(ROWS):
        for x in range(COLS):
            px = x * CELL
            py = y * CELL
            if maze[y][x] == 1:
                pygame.draw.rect(screen, WALL_COLOR, (px, py, CELL, CELL))
                pygame.draw.rect(screen, (40, 40, 200), (px, py, CELL, CELL), 1)

    # 豆子
    for (dx, dy) in dots:
        cx = dx * CELL + CELL // 2
        cy = dy * CELL + CELL // 2
        if (dx, dy) in power_dots:
            # 大力丸：大而闪烁
            pulse = 3 + int(abs(pygame.time.get_ticks() % 1000 - 500) / 200)
            pygame.draw.circle(screen, YELLOW, (cx, cy), pulse)
        else:
            pygame.draw.circle(screen, WHITE, (cx, cy), 2)


def show_text(screen, text, size, color, y_offset=0):
    font = pygame.font.Font(None, size)
    surf = font.render(text, True, color)
    rect = surf.get_rect(center=(WIDTH // 2, HEIGHT // 2 + y_offset))
    screen.blit(surf, rect)


def main():
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("吃豆子 Pac-Man")
    clock = pygame.time.Clock()

    # 初始位置
    pacman = Pacman(10, 9)
    ghost = Ghost(9, 5, RED)
    dots, power_dots = init_dots(MAZE)
    score = 0
    lives = 3
    game_over = False
    win = False

    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if game_over or win:
                    if event.key == pygame.K_r:
                        # 重新开始
                        pacman = Pacman(10, 9)
                        ghost = Ghost(9, 5, RED)
                        dots, power_dots = init_dots(MAZE)
                        score = 0
                        lives = 3
                        game_over = False
                        win = False
                    elif event.key == pygame.K_q:
                        running = False
                else:
                    if event.key == pygame.K_UP:
                        pacman.set_direction(UP)
                    elif event.key == pygame.K_DOWN:
                        pacman.set_direction(DOWN)
                    elif event.key == pygame.K_LEFT:
                        pacman.set_direction(LEFT)
                    elif event.key == pygame.K_RIGHT:
                        pacman.set_direction(RIGHT)

        if not game_over and not win:
            pacman.move(MAZE)
            ghost.move(MAZE, pacman.x, pacman.y)

            # 吃豆子
            pos = (pacman.x, pacman.y)
            if pos in dots:
                dots.remove(pos)
                if pos in power_dots:
                    power_dots.remove(pos)
                    score += 50
                    ghost.frightened = True
                    ghost.fright_timer = 50  # 5秒
                else:
                    score += 10

            # 胜利
            if not dots:
                win = True

            # 碰撞检测
            if pacman.x == ghost.x and pacman.y == ghost.y:
                if ghost.frightened:
                    # 吃掉幽灵
                    score += 200
                    ghost.x, ghost.y = 9, 5
                    ghost.frightened = False
                else:
                    lives -= 1
                    if lives <= 0:
                        game_over = True
                    else:
                        # 重置位置
                        pacman = Pacman(10, 9)
                        ghost = Ghost(9, 5, RED)

        # 绘制
        screen.fill(BLACK)
        draw_maze(screen, MAZE, dots, power_dots)
        pacman.draw(screen)
        ghost.draw(screen)

        # HUD
        font = pygame.font.Font(None, 28)
        score_text = font.render(f"Score: {score}", True, WHITE)
        lives_text = font.render(f"Lives: {lives}", True, WHITE)
        screen.blit(score_text, (10, ROWS * CELL + 8))
        screen.blit(lives_text, (WIDTH - 120, ROWS * CELL + 8))

        if game_over:
            show_text(screen, "GAME OVER", 48, RED, -20)
            show_text(screen, f"Score: {score}  Press R to restart, Q to quit", 24, WHITE, 25)
        elif win:
            show_text(screen, "YOU WIN!", 48, YELLOW, -20)
            show_text(screen, f"Score: {score}  Press R to restart, Q to quit", 24, WHITE, 25)

        pygame.display.flip()
        clock.tick(FPS)

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
