# ContactGlove Python SDK V2

[English](https://github.com/MeltInterfaceTechnologies/ContactGloveSDKv2Python/blob/main/README.md) | 日本語

DivingStationからContactGlove3 ProのデータをOSCで受信するPython SDKです。グローブ、エルゴノミクス、骨格、センサー、コントローラーのデータを取得またはコールバックで受信でき、振動も要求できます。

## 必要環境

- Python 3.10以上。Windows 11、macOS、Ubuntuで動作確認済みです。
- ContactGlove3 Proと、インストール・起動済みのDivingStation。DivingStationで接続を設定し、必要に応じて承認してください。
- `python-osc>=1.7.5`と`matplotlib>=3.7.5`は自動インストールされます。matplotlibはviewerサンプルで使用します。

## インストール

### PyPIから

```sh
python -m pip install contactglovesdk
```

### 配布ZIPから

配布ZIPを展開し、同梱のwheelをインストールします。`X.Y.Z`はファイルのバージョンに置き換えてください。

```sh
python -m pip install ./contactglovesdk-X.Y.Z-py3-none-any.whl
```

## データの受信

DivingStationを起動してグローブを接続してください。以下は同じPC上のDivingStationの既定OSCポートを使用します。求められた場合はDivingStationで接続を承認してください。Ctrl+Cで終了します。

```python
import time
from contactglovesdk import ContactGloveClient, Host

host = Host("DivingStation", "127.0.0.1", 25791)
with ContactGloveClient() as client:
    client.register_callback_for_glove_data_stream(print)
    client.connect_to_host(host)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        client.disconnect(host)
```

## ドキュメント・問い合わせ

- [接続設定・使い方・トラブルシューティング](https://docs.melt-interface-technologies.com/ja/docs/contact/sdks/contact-glove-v2-python)
- [APIリファレンス](https://docs.melt-interface-technologies.com/ja/docs/contact/sdks/contact-glove-v2-python/api)
- [お問い合わせ](https://melt-interface-technologies.com/contact/)
- [開発者向けガイド](https://github.com/MeltInterfaceTechnologies/ContactGloveSDKv2Python/blob/main/DEVELOPMENT_JA.md)

配布パッケージの`doc/`にもAPIリファレンスとライセンス文書が含まれます。

## ライセンス

SDKは[Apache License 2.0](https://github.com/MeltInterfaceTechnologies/ContactGloveSDKv2Python/blob/main/LICENSE.md)で提供します。著作権表示と依存ライブラリのライセンスは[NOTICE](https://github.com/MeltInterfaceTechnologies/ContactGloveSDKv2Python/blob/main/NOTICE.md)および[サードパーティ通知](https://github.com/MeltInterfaceTechnologies/ContactGloveSDKv2Python/blob/main/THIRD_PARTY_NOTICES.md)を参照してください。
