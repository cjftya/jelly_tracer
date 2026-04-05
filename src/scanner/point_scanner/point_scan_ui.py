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

        self.current_incidents = None  # FusionCoreEngine에서 전달받을 데이터
        self.HEADER_W = 120            # 스레드 이름을 위한 왼쪽 여백 (약간 줄임)
        self.DASHBOARD_H = 150         # 지연 뷰 높이 축소 (기존 210 -> 150)

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

    def on_chart_view_resize(self, event, canvas: ctk.CTkCanvas):
        self.draw(canvas)
    
    def on_chart_view_drag_start(self, event, canvas: ctk.CTkCanvas):
        # 픽셀 좌표를 보정하여 드래그 시작 (지연 뷰 영역 내에서만 동작하도록 필요 시 체크 가능)
        self.drag_start_x = event.x

    def on_chart_view_drag(self, event, canvas: ctk.CTkCanvas):
        if not self.milestones_registry: return

        # 픽셀 변화량 계산
        dx = event.x - self.drag_start_x
        self.drag_start_x = event.x # 기준점 즉시 갱신

        W = canvas.winfo_width()
        PX = 2 # 지연 뷰 시작점과 일치하도록 고정
        CHART_W = W - (PX * 2) - 20
        if CHART_W <= 0: return

        # 픽셀 변화량을 인덱스 변화량으로 변환
        current_range = self.zoom_end - self.zoom_start
        shift = (dx / CHART_W) * current_range
        
        # 새로운 범위 계산 (데이터 끝단에 걸리면 멈춤)
        max_idx = float(len(self.milestones_registry) - 1)
        new_start = max(0.0, min(max_idx - current_range, self.zoom_start - shift))
        new_end = new_start + current_range

        # 상태 업데이트
        self.zoom_start = new_start
        self.zoom_end = new_end
        self.selected_start_index = int(self.zoom_start)
        self.selected_end_index = int(self.zoom_end)

        self.draw(canvas)

    def on_chart_view_zoom(self, event, canvas: ctk.CTkCanvas):
        if not self.milestones_registry: return

        zoom_factor = 0.7 if event.delta > 0 else 1.4 # 위로 굴리면 확대
        
        W = canvas.winfo_width()
        PX = 2
        CHART_W = W - (PX * 2) - 20
        if CHART_W <= 0: return

        # 마우스 위치 비율 계산 (0.0 ~ 1.0)
        rel_x = (event.x - PX) / CHART_W
        rel_x = max(0.0, min(1.0, rel_x))

        current_range = self.zoom_end - self.zoom_start
        cursor_idx = self.zoom_start + (rel_x * current_range)
        new_range = current_range * zoom_factor

        # 최소/최대 줌 제한
        max_idx = float(len(self.milestones_registry) - 1)
        if new_range < 1.0: new_range = 1.0
        if new_range > max_idx: new_range = max_idx

        # 마우스 위치를 축으로 새로운 시작/끝점 계산
        new_start = max(0.0, cursor_idx - (rel_x * new_range))
        new_end = min(max_idx, new_start + new_range)

        # 상태 업데이트
        self.zoom_start = new_start
        self.zoom_end = new_end
        self.selected_start_index = int(self.zoom_start)
        self.selected_end_index = int(self.zoom_end)

        self.draw(canvas)

    # ---------------------------------------------------------
    # 1. 통합 드로잉 관제 (기존 draw_latency_distribution 대체 호출용)
    # ---------------------------------------------------------
    def draw(self, canvas: ctk.CTkCanvas, incidents_data=None):
        if incidents_data:
            self.current_incidents = incidents_data
            
        # 1. 상단 지연 뷰 그리기 (지연 뷰의 데이터 기반으로 포커스 정보 반환)
        last_focus_info = self.draw_latency_distribution(canvas)
        if last_focus_info is None:
            return
        
        # 2. 하단 슬라이스 뷰 그리기 및 높이 계산
        final_y = last_focus_info["START_Y"]
        if self.current_incidents:
            final_y = self.draw_slice(canvas, last_focus_info)
        
        # 3. 캔버스 높이 및 스크롤 영역 동적 조정
        W = canvas.winfo_width()
        # 캔버스 위젯 자체의 높이를 내용에 맞게 조정하여 ScrollableFrame 내에서 전체가 보이도록 함
        new_height = max(200, final_y + 50)
        canvas.configure(height=new_height, scrollregion=(0, 0, W, new_height))
        canvas.update_idletasks()
        
        # 만약 캔버스 시각적 높이가 작다면 고정값 또는 내용에 맞춰 조정 가능
        # (하지만 여기서는 scrollregion 갱신으로 스크롤바가 작동하도록 함)

    # ---------------------------------------------------------
    # 2. 지연 뷰
    # ---------------------------------------------------------
    def draw_latency_distribution(self, canvas: ctk.CTkCanvas):
        canvas.delete("all")

        # 1. 기초 레이아웃 설정
        W = canvas.winfo_width() if canvas.winfo_width() > 1 else 1000
        H = self.DASHBOARD_H
        PX = 2  # 지연 분포 뷰는 왼쪽 여백 없이 전체 폭 사용
        PY_TOP, PY_BOT = 45, 15  # 여백 축소
        CHART_W, CHART_H = W - (PX * 2) - 20, H - PY_TOP - PY_BOT
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

        return {
            "focus_start": focus_start,
            "focus_end": focus_end,
            "CHART_W": CHART_W,
            "PX": PX,
            "START_Y": BASE_Y + 40 # 시간 텍스트 아래에서 여유 있게 시작
        }

    # ---------------------------------------------------------
    # 3. 슬라이스 뷰 (신규 추가)
    # ---------------------------------------------------------
    def draw_slice(self, canvas: ctk.CTkCanvas, focus_info):
        """Normal Shadow 대조 및 Ghost Gap을 포함한 슬라이스 렌더링"""
        f_start = focus_info["focus_start"]
        f_end = focus_info["focus_end"]
        f_dur = f_end - f_start
        PX = focus_info["PX"]
        CHART_W = focus_info["CHART_W"]
        y_cursor = focus_info["START_Y"]
        
        current_thread = ""
        
        # 헬퍼: 나노초 시간을 픽셀 X 좌표로 변환
        def get_x(ts):
            return PX + ((ts - f_start) / f_dur) * CHART_W

        # 구분선 (슬라이스 뷰 상단)
        canvas.create_line(10, y_cursor - 10, canvas.winfo_width() - 10, y_cursor - 10, fill="#30363D")
        canvas.create_text(PX, y_cursor - 5, text="THREAD TIMELINE (Shadow: Normal / Box: Slow Actual)", 
                           fill="#8B949E", anchor="nw", font=("Segoe UI", 8, "bold"))
        y_cursor += 30

        for inc in self.current_incidents.get("incidents", []):
            # X 좌표 계산 (Slow 기준 시작 시점으로 정렬)
            x_start = get_x(inc['start_timestamp'])
            x_end_s = get_x(inc['start_timestamp'] + inc['duration_ns'])
            
            # 1. Normal Baseline (그림자) - Slow와 동일한 위치에서 시작, duration만 다름
            norm_info = inc.get("normal_info")
            if norm_info and norm_info['duration_ns'] > 0:
                x_end_n = get_x(inc['start_timestamp'] + norm_info['duration_ns'])
                # Baseline은 아래쪽에 얇은 초록색으로 표시
                if not (x_end_n < PX or x_start > PX + CHART_W):
                    canvas.create_rectangle(x_start, y_cursor + 14, x_end_n, y_cursor + 18, 
                                             fill="#3FB950", outline="") 

            # 2. Slow Actual (실제 박스) - 위쪽에 메인 파란색 박스로 표시
            if not (x_end_s < PX or x_start > PX + CHART_W):
                is_ghost = inc.get('is_ghost_incident', False)
                # 일반 슬로우는 파랑, 고스트는 빨강 계열로 가독성 확보
                color = "#f85149" if is_ghost else "#388bfd" 
                
                # 메인 박스 렌더링
                canvas.create_rectangle(x_start, y_cursor, x_end_s, y_cursor + 14, 
                                         fill=color, outline="white", width=0.5)
                
                # 이름 표시 (슬라이스 이름 + 스레드 이름 조합)
                slice_id = inc['slice_id']
                full_name = f"[{slice_id}] {inc['slice_name']} ({inc['thread_name']})"
                canvas.create_text(x_start + 5, y_cursor + 7, text=full_name, 
                                   fill="white", font=("Segoe UI", 8), anchor="w")

            y_cursor += 22

        return y_cursor