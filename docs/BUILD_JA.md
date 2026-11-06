# ビルド・テスト・CI

[English](BUILD.md) | 日本語

Python 3.10以上で、以下のコマンドを実行します。

```sh
python -m pip install --upgrade build wheel twine
python -m pip install python-osc matplotlib
python scripts/gen_api_doc.py --check
python -m unittest discover -s tests
python -m build
python -m twine check --strict dist/*.whl dist/*.tar.gz
python -m pip install dist/contactglovesdk-X.Y.Z-py3-none-any.whl
python examples/test_smoke.py
python scripts/make_dist_package.py --skip-build
python scripts/check_dist_licenses.py
```

`X.Y.Z`はビルドしたバージョンに置き換えてください。スモークテストにはDivingStationは不要です。`examples/basic_usage.py`と`examples/simple_receive.py`には起動済みのDivingStationと接続済みのグローブが必要です。viewerの設定はそのREADMEを参照してください。

依存関係は`uv sync`でもインストールできます。wheelのみをビルドするには`python -m build --wheel`を実行します。出力は`dist/contactglovesdk-X.Y.Z-py3-none-any.whl`です。

CIはこれらのチェックとwheel・sdistのビルドを行い、配布ZIPとそのSHA-256をActions artifactとして保存します。リリースや公開は行いません。ZIPにはwheel、日英README、サンプル、生成済みAPIリファレンス、ライセンス文書を含みます。`--skip-build`は`dist/`に対象wheelが一つだけあることを要求します。省略した場合はAPI文書の確認後にwheelをビルドします。

出力は`dist/ContactGloveSDKv2Python-X.Y.Z.zip`とその`.zip.sha256`です。CIのartifact名は`ContactGloveSDKv2Python-<commit SHA>`で、保存期間はリポジトリのActions設定に従います。artifactにはsdistやリポジトリ一式を含めません。ZIPからは`examples/test_smoke.py`など社内・CI専用の内容を除外します。pure Pythonのwheelには実行に必要なコードを含みます。

ZIP作成時には、READMEの言語切り替え・ライセンス・APIリンクを同梱ファイルへのリンクに変換し、オフラインでも開けるようにします。開発文書は同梱しないため、開発ガイドへのリンクは省きます。リポジトリのREADMEとwheelのメタデータは、PyPI用の絶対URLを維持します。

ZIPのタイムスタンプ、パーミッション、順序は固定されます。wheelとZIPの再現性を比較するには、OS、Python、zlib、ビルドツールのバージョンと`SOURCE_DATE_EPOCH`を揃えてください。チェックサムはActionsの外側のartifactではなく、配布ZIP自体のものです。
