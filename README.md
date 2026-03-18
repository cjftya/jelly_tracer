```text
  ╭━━━╮╭╮  ╭╮╭━━━╮╭━━╮╭━━━╮╭━╮  ╭╮     ╭━━━╮╭━━━╮╭━━━╮╭━━━╮
  ┃╭━━╯┃┃  ┃┃┃╭━╮┃╰┫┣╯┃╭━╮┃┃┃╰╮ ┃┃     ┃╭━╮┃┃╭━╮┃┃╭━╮┃┃╭━━╯
  ┃╰━━╮┃┃  ┃┃╰━╮┃┃ ┃┃ ┃┃ ┃┃┃╭╮╰╮┃┃     ┃┃ ╰╯┃┃ ┃┃┃╰━╯┃┃╰━━╮
  ┃╭━━╯┃┃  ┃┃┃╰━╯┃ ┃┃ ┃┃ ┃┃┃┃╰╮╰╯┃     ┃┃ ╭╮┃┃ ┃┃┃╭╮╭╯┃╭━━╯
  ┃┃   ┃╰━━╯┃╰━━━╯╭┫┣╮┃╰━╯┃┃┃ ╰╮ ┃     ┃╰━╯┃┃╰━╯┃┃┃┃╰╮┃╰━━╮
  ╰╯   ╰━━━━╯     ╰━━╯╰━━━╯╰╯  ╰━╯     ╰━━━╯╰━━━╯╰╯╰━╯╰━━━╯
                                       ───────────────
      ╭━━━╮   ╭╮  ╭━━━╮                🔎 POINT-SCAN (L1)
      ╰━━╮┃  ╭╯╰╮ ┃╭━╮┃                🔬 INSIGHT-SCAN (L2)
       ╭━━╯┃ ╰╮╭╯ ┃┃ ┃┃                ⚖️ FINAL VERDICT
       ╰━━╮┃  ╰╯  ┃┃ ┃┃                ───────────────
      ╭━━━╯┃      ┃╰━╯┃       "Smooth Intelligence, Sharp Results."
      ╰━━━━╯      ╰━━━╯

```

# 🕵️‍♂️ Fusion-Core 3.0: Android Performance Forensic Engine ⚡

> **"Every lag leaves a trace. We find the smoking gun."** > 안드로이드 시스템의 심연(Deep-Dive)을 파헤쳐 지연의 근본 원인을 확정하는 AI 기반 디지털 포렌식 엔진입니다.

---

## 🌟 Overview: The New Standard of Profiling
**Fusion-Core 3.0**은 기존의 단순한 트레이스 뷰어를 넘어, 자율적으로 병목을 추적하고 판결을 내리는 **지능형 수사 파이프라인**입니다. Qwen 3 Flash의 기민한 정찰력과 DeepSeek-R1의 냉철한 분석력을 결합하여, 수천만 개의 이벤트 속에서 단 10k 토큰 내외의 핵심 증거만으로 진실을 인양합니다.

---

## 🎯 Project Concept: "Search & Destroy"
본 프로젝트는 **'반증 불가능한 물리적 증거'**만을 신봉합니다.
* **Precision Targeting:** L1 정찰을 통해 지연이 발생한 특정 윈도우를 나노초($ns$) 단위로 정밀 타격합니다.
* **Evidence-First Verdict:** AI의 막연한 추측을 배제하고, SQL 쿼리로 증명된 물리적 수치($ms$)만을 근거로 기소장을 작성합니다.

---

## 🚀 Key Value Propositions
* **🎯 8-Round Iterative Targeting (L1):** 8차례의 반복 추론(CoT)을 통해 노이즈를 걷어내고 최적의 수사 범위를 확정합니다.
* **⚖️ Dual-Phase Evidence Audit (L2):** 탐사와 검증의 2단계를 거쳐, 1단계 가설이 실제 데이터와 일치하는지 '자기 비판적 부검'을 수행합니다.
* **🔋 Token-Efficient Infrastructure:** 6GB VRAM 환경에서도 안정적인 추론이 가능하도록 '생각 아카이브' 및 '데이터 하드캡' 기술을 적용했습니다.
* **🧬 Multi-Layer Correlation:** 함수 실행(`v_stack`), 락 경합(`locks`), 시스템 부하(`neighbors`), 스케줄링 상태(`rhythm`)를 입체적으로 연결합니다.

---

## 🏛️ Core Architecture & Workflow

### 🛰️ Layer 1: The Scout (Point-Scan)
* **Core Module:** `PointScanner`
* **Investigation Strategy:** 델타 분석 및 8라운드 반복 포위망(Iterative Funnel) 추론 전략
* **Deliverables:** 정밀 타겟 윈도우 좌표와 `pivot_candidates`가 포함된 마스터 브리프(Master Brief) 산출

### 🔬 Layer 2: The Pathologist (Insight-Scan)
* **Core Module:** `InsightScanner`
* **Investigation Strategy:** 5대 전문 API를 통한 심연 드릴링(Drilling) 및 2단계 최종 판결(Final Verdict)
* **Forensic Metrics:**
    1. **Vertical Stacks:** 실행 지연의 약 80%를 설명하는 상위 25개 핵심 함수 추출
    2. **Lock Contention:** 스레드 중단(Stall)을 유발하는 상위 10개 락(Lock) 경합 식별
    3. **CPU Neighbors:** 외부 프로세스 간섭으로 인한 CPU 자원 기아(Starvation) 현상 탐지
    4. **Thread Rhythm:** 스레드의 상태 천이(Running/Runnable/Sleep) 패턴 정밀 분석
    5. **Binder Payload:** IPC 통신 오버헤드 및 트랜잭션 지연 시간 검증

---

## 🛠️ Forensic Infrastructure
* **AI Engine:** Ollama (DeepSeek-R1-8B & Qwen3-8B)
* **Context Guard:** 24,576 Tokens (Smart Trimming 적용)
* **Data Storage:** 수사 정황 및 AI의 고뇌(Thinking)를 박제하는 `FusionCoreDataCollector`

---

## 🏁 Roadmap
* **✅ Phase 1:** L1/L2 하이브리드 파이프라인 및 5대 심연 API 구축
* **🔄 Phase 2:** 수사 기록 자동 아카이빙 및 L1-L2 핸드오버 무결성 확보
* **🚀 Phase 3:** 멀티 트레이스 Diff 분석 및 커널 스케줄러 전문 분석 모듈 확장

---

## 👥 Contributors

- **cjftya**: AI-Driven Performance Forensic Expert & Lead Architect