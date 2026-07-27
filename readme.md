# Ax-RnD-PARKING

휴대폰 웹앱 카메라로 컴퓨터에 재생 중인 CCTV 주차장 화면을 촬영하고, 5분 간격으로 프레임 1장을 분석해 주차면별 점유 상태와 전체 점유율을 보여주는 MVP입니다.

교수님 예시 `02_yolov8n-seg.py`를 기준으로 YOLO segmentation mask에서 차량 바닥 footprint를 추정하고, 사용자가 등록한 주차면 polygon과의 교차 비율로 점유 상태를 판단합니다.

## 현재 구현 상태

- FastAPI 서버와 브라우저 웹앱
- 휴대폰 후면 카메라 우선 연결
- 기준 프레임 캡처
- 주차면별 4점 polygon 등록, ID 입력, 수정, 삭제
- 설정 JSON 저장 및 불러오기
- 수동 분석과 기본 5분 간격 자동 분석
- YOLOv8n segmentation 차량 분석
- `occupied`, `empty`, `unknown` 판정
- 전체 점유율과 마지막 분석 시각 표시
- CSV 및 JSONL 분석 로그
- 캡처 이미지 최근 10장 보관 및 오래된 이미지 자동 삭제
- 데스크톱/모바일 반응형 화면

실제 CCTV 스트림 직접 연결, 자동 주차면 인식, 상태 smoothing, HTTPS 구성은 현재 MVP 범위에 포함하지 않았습니다.

## 프로젝트 구조

```text
Ax-RnD-PARKING/
├─ app/
│  └─ static/
│     ├─ index.html
│     ├─ styles.css
│     └─ app.js
├─ config/
│  ├─ parking_config.example.json
│  └─ parking_config.json          # 실행 중 생성, Git 제외
├─ data/                           # 테스트 영상 위치
├─ models/
│  └─ yolov8n-seg.pt              # Git 제외
├─ outputs/
│  ├─ logs/
│  └─ snapshots/                  # 최근 10장만 유지
├─ src/
│  ├─ analyzer.py
│  ├─ config_store.py
│  ├─ occupancy.py
│  └─ server.py
├─ tests/
│  ├─ test_config_store.py
│  ├─ test_occupancy.py
│  ├─ test_server.py
│  └─ smoke_api.py
├─ requirements.txt
└─ run.ps1
```

## 실행

현재 프로젝트에는 `.venv`와 `models/yolov8n-seg.pt`가 준비되어 있으므로 PowerShell에서 다음 명령으로 실행할 수 있습니다.

```powershell
cd C:\Project\Ax-RnD-PARKING
.\run.ps1
```

PC 브라우저:

```text
http://127.0.0.1:8000
```

같은 Wi-Fi의 휴대폰:

```text
http://PC_IP:8000
```

휴대폰 브라우저는 보안 정책상 일반 HTTP 주소에서 카메라 권한을 차단할 수 있습니다. PC의 `localhost`에서는 먼저 전체 기능을 검증할 수 있으며, 휴대폰 실기기 테스트 전에는 로컬 HTTPS 인증서 또는 개발용 HTTPS 터널 구성이 필요합니다.

새 환경에서 다시 설치할 때는 다음 명령을 사용합니다.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

모델 파일은 `models/yolov8n-seg.pt`에 둡니다.

## 사용 흐름

1. `카메라 연결`을 눌러 후면 카메라를 연결합니다.
2. 컴퓨터에서 재생 중인 CCTV 화면이 카메라에 맞도록 휴대폰을 고정합니다.
3. `기준 프레임 캡처`를 누릅니다.
4. 주차면 모서리 네 점을 시계 방향으로 선택합니다.
5. `A1` 같은 ID를 입력하고 `주차면 추가`를 누릅니다.
6. 필요한 주차면을 모두 등록한 뒤 `설정 저장`을 누릅니다.
7. `모니터링 시작`을 누릅니다.
8. 시작 즉시 한 번 분석하고, 이후 기본 5분 간격으로 자동 분석합니다.

휴대폰 위치나 촬영 각도가 달라지면 기준 프레임과 주차면 좌표를 다시 설정해야 합니다.

## 점유 판정

기본 설정값:

```json
{
  "analysis_interval_minutes": 5,
  "snapshot_retention_count": 10,
  "occupancy_threshold": 0.15,
  "unknown_threshold": 0.05,
  "confidence_threshold": 0.25,
  "image_size": 960
}
```

- `occupied`: 차량 footprint가 주차면의 15% 이상과 겹침
- `unknown`: 겹침이 5% 이상 15% 미만이거나 모델을 사용할 수 없음
- `empty`: 겹침이 5% 미만

점유율은 `occupied / 전체 주차면 * 100`으로 계산하며 `unknown`은 별도 수치로 표시합니다.

## API

- `GET /health`: 서버, 모델 파일, 주차면 수 확인
- `GET /api/config`: 현재 설정 불러오기
- `POST /api/config`: 주차면과 분석 설정 저장
- `POST /api/analyze`: 이미지 1장 업로드 및 점유 분석
- `GET /api/results/latest`: 최근 분석 결과
- `GET /api/snapshots`: 최근 캡처 목록
- `GET /api/snapshots/{filename}`: 캡처 이미지 확인

분석 로그:

- `outputs/logs/analysis_results.jsonl`
- `outputs/logs/analysis_results.csv`

## 테스트

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe tests\smoke_api.py
node --check app\static\app.js
```

현재 자동 검증 결과:

- 단위 테스트 7개 통과
- 서버 `/health` 및 첫 화면 HTTP 200 확인
- 실제 `yolov8n-seg.pt` 로딩과 이미지 분석 응답 확인
- 최근 캡처 10장 보관 로직 확인
- 데스크톱 1440px, 모바일 390px 화면에서 가로 넘침 없음 확인

현장 정확도는 테스트 CCTV 영상과 실제 휴대폰 촬영 조건에서 별도로 측정해야 합니다. 진행 여부는 `checklist.md`에서 계속 관리합니다.
