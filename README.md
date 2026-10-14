# Maya AS–Mixamo Bridge

Maya 2025에서 AdvancedSkeleton(AS) 캐릭터와 Mixamo 계열 애니메이션을 한 장면 안에서 연결하는 Python 툴입니다. 제공된 `Belato01` AS 구조와 `TeamExtra01` 하이브리드 컨트롤 리그를 실제 파일 기준으로 프로파일링했습니다.

## 설치

1. 저장소를 내려받습니다.
2. Maya Script Editor의 **Python** 탭에서 아래 코드를 실행합니다.

```python
exec(open(r"C:\path\to\maya-AS-mixamo-bridge\install.py", encoding="utf-8").read())
```

현재 Maya 사용자 `scripts` 폴더에 패키지가 설치되고 **AS Mixamo** 선반 버튼이 추가됩니다. 직접 실행하려면 다음 코드를 사용합니다.

```python
import as_mixamo_bridge.ui as ui
ui.show()
```

## 권장 작업 흐름

1. AS 캐릭터의 아무 컨트롤이나 선택합니다.
2. **Mixamo Work Mode**를 누릅니다. 임시 Mixamo 스타일 바디 컨트롤이 생성되고 기존 AS 바디 컨트롤은 선택 보호됩니다. 얼굴 컨트롤은 계속 사용할 수 있습니다.
3. 임시 컨트롤로 작업하거나 **Apply Mixamo Animation**에서 `.fbx`, `.mb`, `.ma`를 선택합니다.
4. 결과를 확인하고 **Bake to AS**를 누릅니다. 평가된 AS 결과가 새 override 애니메이션 레이어에 매 프레임 베이크되고 변형 조인트가 자동 검증됩니다.
5. 만족하면 Maya의 **Save As**로 새 파일을 저장합니다. 취소하려면 **Restore Pre-Conversion State**를 누릅니다.

네임스페이스, 캐릭터의 월드 위치·회전·스케일, 0,0,0 배치는 사용자가 맞출 필요가 없습니다. 탐색은 선택한 캐릭터 계층 안에서만 수행됩니다.

## 프레임과 FPS

- 기본값은 **소스 키의 프레임 번호 보존**입니다. 예: `1001–1120`은 장면 FPS가 달라도 `1001–1120`으로 들어갑니다.
- Advanced에서 **재생 시간 보존**을 선택하면 소스/대상 FPS 비율에 따라 종료 프레임과 샘플 위치를 계산합니다.
- 장면 FPS는 자동 변경하지 않습니다. **Change scene FPS explicitly**를 켠 경우에만 확인창을 거쳐 변경하며, 키 번호는 유지합니다.
- 최종 베이크는 정확도를 우선해 정수 프레임마다 키를 생성합니다.

## 안전성과 복구

- 원본 AS 키와 레이어를 삭제하지 않습니다.
- 결과는 새 override 레이어에만 기록됩니다.
- 임시 노드, 연결, 디스플레이 레이어와 원래 연결 상태는 세션 manifest에 기록됩니다.
- 성공한 베이크도 명시적 Restore가 가능하며, 즉시 작업은 Maya Undo 한 번으로 되돌릴 수 있습니다.
- 얼굴 리그, 얼굴 키, blendShape는 전송 대상에서 제외되고 보존됩니다.
- 입력 `.mb`/`.fbx`는 덮어쓰거나 저장하지 않습니다.

## 현재 지원 범위와 한계

- 검증 호스트: Maya 2025.
- AS 프로필: `Belato01_rig_v01_w01` 계열 이름과 구조.
- 스튜디오 Mixamo 프로필: `TeamExtra01_rig_v01` 계열 하이브리드 컨트롤 리그.
- 일반 Mixamo FBX: 표준 `Hips`, `LeftArm`, `LeftUpLeg` 등의 조인트 구조.
- Raw FBX에는 IK/FK 의도가 없으므로 기본 정책은 **팔 FK / 다리 IK**입니다.
- 선언되지 않은 커스텀 보조 컨트롤, 소품, 얼굴 애니메이션은 옮기지 않습니다.
- 다른 버전의 AS 또는 스튜디오 리그에서 필수 노드/속성이 다르면 안전하게 중단됩니다. 이름을 추측해 다른 노드에 키를 쓰지 않습니다.
- Ornatrix/V-Ray가 없는 테스트 환경에서는 파일을 열 때 Maya 경고가 나올 수 있습니다. 바디 변환은 계속할 수 있지만, 플러그인이 없는 상태에서 원본 파일을 저장하지 마세요.

설계와 검증 기준은 [design specification](docs/superpowers/specs/2026-10-14-as-mixamo-bridge-design.md), 자동 테스트 방법은 [docs/testing.md](docs/testing.md)에 있습니다.
