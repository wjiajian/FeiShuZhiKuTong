# -*- coding: utf-8 -*-

"""
获取飞书企业自建应用的 tenant_access_token。

通过 App ID 和 App Secret 调用飞书开放平台接口，获取应用级别的访问凭证。
token 有效期为 2 小时（7200 秒），过期后需重新获取。

使用前请确保:
- 已安装 requests 库: `pip install requests`
"""

import requests
from typing import Optional


def get_feishu_tenant_access_token(app_id: str, app_secret: str) -> Optional[str]:
    """
    获取飞书 tenant_access_token（应用级别凭证，无需用户授权）。

    Args:
        app_id (str): 飞书应用的 App ID。
        app_secret (str): 飞书应用的 App Secret。

    Returns:
        成功返回 tenant_access_token 字符串，失败返回 None。
    """
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    payload = {
        "app_id": app_id,
        "app_secret": app_secret,
    }

    try:
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()

        if data.get("code") == 0:
            token = data.get("tenant_access_token")
            print("成功获取飞书 tenant_access_token。")
            return token
        else:
            print(f"获取 tenant_access_token 失败: code={data.get('code')}, msg={data.get('msg')}")
            return None

    except requests.RequestException as e:
        print(f"获取 tenant_access_token 时网络请求失败: {e}")
        return None
    except ValueError as e:
        print(f"获取 tenant_access_token 时解析响应失败: {e}")
        return None


if __name__ == "__main__":
    # 示例用法，请替换为实际的 App ID 和 App Secret
    APP_ID = ""
    APP_SECRET = ""

    if APP_ID and APP_SECRET:
        token = get_feishu_tenant_access_token(APP_ID, APP_SECRET)
        if token:
            print(f"Token: {token[:20]}...")
    else:
        print("请先设置 APP_ID 和 APP_SECRET。")
