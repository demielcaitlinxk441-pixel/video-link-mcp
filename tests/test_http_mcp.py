from unittest.mock import patch
import unittest

import server


class HttpMcpTests(unittest.TestCase):
    def test_default_mode_keeps_stdio_transport(self):
        config = server.parse_runtime_config([])

        self.assertEqual(config.transport, 'stdio')
        self.assertEqual(config.port, 8000)

    def test_rejects_port_outside_valid_tcp_range(self):
        with self.assertRaises(SystemExit):
            server.parse_runtime_config(['--transport', 'http', '--port', '70000'])

    def test_streamable_http_app_exposes_mcp_route(self):
        app = server.mcp.streamable_http_app()
        paths = {route.path for route in app.routes}

        self.assertIn('/mcp', paths)

    def test_http_mode_uses_streamable_http_and_localhost_port(self):
        config = server.parse_runtime_config(['--transport', 'http', '--port', '8765'])

        self.assertEqual(config.transport, 'streamable-http')
        self.assertEqual(config.port, 8765)

        with patch.object(server.mcp, 'run') as run:
            server.run_server(config)

        self.assertEqual(server.mcp.settings.host, '127.0.0.1')
        self.assertEqual(server.mcp.settings.port, 8765)
        run.assert_called_once_with(transport='streamable-http')


if __name__ == '__main__':
    unittest.main()
