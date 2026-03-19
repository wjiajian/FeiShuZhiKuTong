import unittest
from unittest.mock import Mock, patch

from feishu.get_token import get_feishu_tenant_access_token


class TestGetFeishuTenantAccessToken(unittest.TestCase):
    @patch("feishu.get_token.requests.post")
    def test_returns_token_on_success(self, mock_post):
        mock_response = Mock()
        mock_response.json.return_value = {"code": 0, "tenant_access_token": "token-123"}
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        token = get_feishu_tenant_access_token("app", "secret")

        self.assertEqual(token, "token-123")
        mock_post.assert_called_once()

    @patch("feishu.get_token.requests.post")
    def test_returns_none_when_api_code_not_zero(self, mock_post):
        mock_response = Mock()
        mock_response.json.return_value = {"code": 999, "msg": "bad auth"}
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        token = get_feishu_tenant_access_token("app", "secret")

        self.assertIsNone(token)

    @patch("feishu.get_token.requests.post")
    def test_returns_none_on_request_exception(self, mock_post):
        import requests

        mock_post.side_effect = requests.RequestException("network down")

        token = get_feishu_tenant_access_token("app", "secret")

        self.assertIsNone(token)

    @patch("feishu.get_token.requests.post")
    def test_returns_none_on_invalid_json(self, mock_post):
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.side_effect = ValueError("invalid json")
        mock_post.return_value = mock_response

        token = get_feishu_tenant_access_token("app", "secret")

        self.assertIsNone(token)


if __name__ == "__main__":
    unittest.main()
