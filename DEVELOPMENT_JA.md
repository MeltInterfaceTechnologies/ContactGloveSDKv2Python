# 開発者向けガイド

[English](DEVELOPMENT.md) | 日本語

ソースから作業する開発者向けの案内です。利用方法は[README](README_JA.md)を参照してください。

- [ビルド・テスト・CI・配布](docs/BUILD.md)（[日本語](docs/BUILD_JA.md)）

`api.md`はdocstringから`python scripts/gen_api_doc.py`で生成します。前文は`contactglovesdk/__init__.py`のモジュールdocstring、リファレンスは各クラス・Enum・例外・メソッドのdocstringから生成されます。生成にはPython標準ライブラリを使い、pdocは使いません。`python scripts/gen_api_doc.py --check`で確認し、CIは未生成または古い場合に失敗します。
