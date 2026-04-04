import tkinter as tk
import customtkinter as ctk

class PointScanUI:
    def __init__(self):
        self.start_time = 0
        self.end_time = 0
        self.milestones_registry = []
        self.milestone_marks = []
        self.max_delay_ratio = 0
        self.selected_start_index = -1
        self.selected_end_index = -1
        
        # Viewport control (floating point for precision)
        self.zoom_start = 0.0
        self.zoom_end = 0.0
        self.drag_start_x = 0

    def set_info(self, milestones_registry, milestone_marks):
        self.milestone_marks = milestone_marks
        self.milestones_registry = milestones_registry
        self.start_time = milestones_registry[0]['ts_s_start']
        self.end_time = milestones_registry[-1]['ts_s_end']
        self.max_delay_ratio = max(item['delay_ratio'] for item in milestones_registry)
        
        # Reset viewport on new data
        self.zoom_start = 0.0
        self.zoom_end = float(len(milestones_registry) - 1)
        self.selected_start_index = 0
        self.selected_end_index = int(self.zoom_end)

    def on_drag_start(self, event):
        self.drag_start_x = event.x

    def on_drag(self, event, canvas: ctk.CTkCanvas):
        if not hasattr(self, 'zoom_start') or not self.milestones_registry:
            return

        # 1. 이동 거리 계산 (픽셀 단위)
        dx = event.x - self.drag_start_x
        self.drag_start_x = event.x # 마지막 위치 갱신

        # 2. 픽셀 거리를 인덱스 범위로 변환
        W = canvas.winfo_width()
        PX = 2
        CHART_W = W - (PX * 2)
        
        current_range = self.zoom_end - self.zoom_start
        # 1픽셀당 몇 개의 인덱스가 들어있는지 계산
        idx_per_pixel = current_range / CHART_W
        
        # 마우스가 오른쪽으로 가면 데이터는 왼쪽으로 밀려야 함 (인덱스 감소)
        shift = dx * idx_per_pixel
        
        # 3. 새로운 범위 계산
        new_start = self.zoom_start - shift
        new_end = self.zoom_end - shift
        
        # 4. 경계값 체크 (전체 데이터 범위를 벗어나지 않게)
        max_idx = float(len(self.milestones_registry) - 1)
        
        if new_start < 0:
            new_start = 0.0
            new_end = current_range
        elif new_end > max_idx:
            new_end = max_idx
            new_start = max_idx - current_range
            
        # 5. 상태 업데이트 및 다시 그리기
        self.zoom_start = new_start
        self.zoom_end = new_end
        self.selected_start_index = int(self.zoom_start)
        self.selected_end_index = int(self.zoom_end)
        
        self.draw_latency_distribution(canvas)

    def on_zoom(self, event, canvas: ctk.CTkCanvas):
        if not self.milestones_registry:
            return

        max_idx = float(len(self.milestones_registry) - 1)

        # 1. 내부 관리용 변수가 없다면 생성 (최초 1회)
        if not hasattr(self, 'zoom_start'):
            self.zoom_start = 0.0
            self.zoom_end = max_idx

        # 2. 마우스 위치 비율 계산
        W = canvas.winfo_width()
        PX = 2
        CHART_W = W - (PX * 2)
        rel_x = (event.x - PX) / CHART_W
        rel_x = max(0.0, min(1.0, rel_x))

        # 3. 현재 실수 범위 계산
        current_range = self.zoom_end - self.zoom_start
        cursor_idx = self.zoom_start + (rel_x * current_range)

        # 4. 줌 배율 적용 (공격적인 배율 유지)
        zoom_factor = 0.7 if event.delta > 0 else 1.4
        new_range = current_range * zoom_factor

        # 5. 범위 제한 (최소 1개 인덱스, 최대 전체 데이터)
        if new_range < 1.0: new_range = 1.0
        if new_range > max_idx + 1: new_range = max_idx + 1

        # 6. 새로운 실수 기반 시작/종료점 계산
        new_start = cursor_idx - (rel_x * new_range)
        new_end = cursor_idx + ((1.0 - rel_x) * new_range)

        # 7. 경계값 고정 (실수 상태로 보관)
        self.zoom_start = max(0.0, new_start)
        self.zoom_end = min(max_idx, new_end)

        # 8. 실제 인덱스 변수에 정수형으로 전달 (그리기 함수에서 사용)
        self.selected_start_index = int(self.zoom_start)
        self.selected_end_index = int(self.zoom_end)

        if self.selected_start_index >= self.selected_end_index:
            if self.selected_end_index < int(max_idx):
                self.selected_end_index += 1
            elif self.selected_start_index > 0:
                self.selected_start_index -= 1

        self.draw_latency_distribution(canvas)

    def draw_latency_distribution(self, canvas: ctk.CTkCanvas, start_m_index: int = -1, end_m_index: int = -1):
        canvas.delete("all")

        if start_m_index != -1 and end_m_index != -1:
            self.selected_start_index = start_m_index
            self.selected_end_index = end_m_index
        
        # 1. 기초 레이아웃 설정
        W = canvas.winfo_width() if canvas.winfo_width() > 1 else 800
        H = canvas.winfo_height() if canvas.winfo_height() > 1 else 210
        PX, PY_TOP, PY_BOT = 2, 70, 25
        CHART_W, CHART_H = W - (PX * 2), H - PY_TOP - PY_BOT
        BASE_Y = PY_TOP + CHART_H
        
        # 데이터 소스
        if not self.milestones_registry:
            canvas.create_text(W/2, H/2, text="WAITING FOR HOTZONE ANALYSIS...", fill="#4B5563")
            return

        hot_segments = []
        if self.selected_start_index != -1 and self.selected_end_index != -1:
            hot_segments = self.milestones_registry[self.selected_start_index : self.selected_end_index + 1]
            
        if len(hot_segments) == 0:
            focus_start = self.start_time
            focus_end = self.end_time
            is_focused = False
        else:
            margin = (self.milestones_registry[0]['ts_s_end'] - self.milestones_registry[0]['ts_s_start']) 
            focus_start = max(self.start_time, hot_segments[0]['ts_s_start'] - margin)
            focus_end = min(self.end_time, hot_segments[-1]['ts_s_end'] + margin)
            is_focused = True

        FOCUS_DUR = focus_end - focus_start

        # 2. 배경 마일스톤 (포커스 범위 안에 있는 것만 그림)
        for m in self.milestone_marks:
            if focus_start <= m['ts_s'] <= focus_end:
                mx = PX + ((m['ts_s'] - focus_start) / FOCUS_DUR) * CHART_W
                canvas.create_line(mx, PY_TOP - 20, mx, BASE_Y, fill="#30363D", dash=(2, 2))
                canvas.create_text(mx + 5, PY_TOP - 35, text=f"📍 {m['name']}", anchor="sw",
                                fill="#58A6FF", font=("Segoe UI", 8, "bold"))

        # 3. 경로(Path) 생성 - 포커스 범위 내 데이터만 맵핑
        points = []
        points.append((PX, BASE_Y))
        
        for item in self.milestones_registry:
            ts_mid = (item['ts_s_start'] + item['ts_s_end']) / 2
            # 포커스 범위 밖의 점은 계산에서 제외 (줌인 효과)
            if focus_start <= ts_mid <= focus_end:
                rate = max(0.0, min(1.0, item['delay_ratio']))
                normalized_rate = rate / self.max_delay_ratio
                x = PX + ((ts_mid - focus_start) / FOCUS_DUR) * CHART_W
                y = BASE_Y - (normalized_rate * CHART_H)
                points.append((x, y))

        points.append((PX + CHART_W, BASE_Y))

        # 4. 렌더링
        if len(points) > 2:
            flattened = [coord for pt in points for coord in pt]
            line_color = "#3FB950" if is_focused else "#238636"
            canvas.create_line(flattened, fill=line_color, width=2.5, smooth=True)

        # 시간 표시 (포커스된 범위의 시간)
        start_name = self.milestones_registry[self.selected_start_index]["name"]
        end_name = self.milestones_registry[self.selected_end_index]["name"]
        label_font = ("Consolas", 8)

        total_observed_delay_ms = sum(item['delay_ms'] for item in hot_segments)
        canvas.create_text(PX + 5, BASE_Y + 10, text=f"Start: {focus_start:,} ns {start_name} {self.selected_start_index}                                Total Observed Delay: {total_observed_delay_ms:.2f} ms", fill="#8B949E", anchor="nw")
        canvas.create_text(PX + CHART_W - 5, BASE_Y + 10, text=f"End: {focus_end:,} ns {end_name} {self.selected_end_index}", fill="#8B949E", anchor="ne")
        
        # 베이스 라인
        canvas.create_line(PX, BASE_Y, PX + CHART_W, BASE_Y, fill="#30363D", width=1)