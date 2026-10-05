"""Read-only engine contract proof (no DB connections or research requests).
Run: PYTHONDONTWRITEBYTECODE=1 /root/behive/.venv/bin/python tests/engine_contract_check.py
Engine location can be overridden with BEHIVE_ENGINE_ROOT.
"""
import asyncio
import os
from pathlib import Path
import subprocess
import tomllib
import unittest
from unittest.mock import patch

ROOT = Path(os.environ.get('BEHIVE_ENGINE_ROOT', '/root/behive'))
LANDING = (Path(__file__).resolve().parents[1] / 'src/pages/index.astro').read_text()


class EngineContracts(unittest.TestCase):
    def test_package_install_metadata(self):
        package = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']
        self.assertEqual(package['name'], 'behive')
        self.assertEqual(package['version'], '0.6.0')
        self.assertEqual(package['requires-python'], '>=3.10')
        self.assertEqual(package['scripts']['behive'], 'behive.cli:main')
        self.assertTrue({'harvest', 'process'}.issubset(package['optional-dependencies']))
        self.assertTrue(any(dep.startswith('fastapi') for dep in package['dependencies']))
        self.assertTrue(any(dep.startswith('uvicorn') for dep in package['dependencies']))

    def test_real_cli_help_and_version(self):
        cli = ROOT / '.venv/bin/behive'
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
        def run(*args):
            return subprocess.check_output([str(cli), *args], text=True, env=env)
        self.assertEqual(run('version').strip(), 'behive 0.6.0')
        help_text = run('research', '--help')
        for flag in ['--depth', '--no-db', '--scale', '--api']:
            self.assertIn(flag, help_text)
        self.assertIn('--quick', run('config', '--help'))
        for flag in ['--host', '--port', '--mcp-port']:
            self.assertIn(flag, run('serve', '--help'))
        self.assertIn('init', run('db', '--help'))

    def test_mcp_real_asgi_metadata_no_database(self):
        import httpx
        from behive.mcp_server import app  # pyright: ignore[reportMissingImports]
        async def exercise():
            # ASGITransport does not execute lifespan. Neither request touches the DB.
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://contract') as client:
                init = await client.post('/mcp', json={'jsonrpc':'2.0', 'id':1, 'method':'initialize'})
                self.assertEqual(init.status_code, 200)
                self.assertEqual(init.json()['result']['serverInfo']['version'], '0.6.0')
                tools = await client.post('/mcp', json={'jsonrpc':'2.0', 'id':2, 'method':'tools/list'})
                self.assertEqual(tools.status_code, 200)
                names = {tool['name'] for tool in tools.json()['result']['tools']}
                self.assertEqual(names, {'research_topic', 'search_knowledge', 'mission_status', 'get_report', 'list_missions'})
                for name in names:
                    self.assertIn(name, LANDING)
        asyncio.run(exercise())

    def test_rest_real_openapi_no_database(self):
        from behive.server import app, ResearchRequest  # pyright: ignore[reportMissingImports]
        schema = app.openapi()
        self.assertEqual(schema['info']['version'], '0.6.0')
        for path in ['/research', '/research/{mission_id}/status', '/research/{mission_id}/events', '/research/{mission_id}/report', '/claims/search', '/missions', '/intelligence/entity/{name}', '/intelligence/network/{name}']:
            self.assertIn(path, schema['paths'])
        request = ResearchRequest(query='your research question', depth=3)
        self.assertEqual(request.effective_query, 'your research question')
        self.assertEqual(request.depth, 3)

    def test_rest_implemented_auth_variable(self):
        from behive.server import verify_auth  # pyright: ignore[reportMissingImports]
        from fastapi import HTTPException
        from starlette.requests import Request
        with patch.dict(os.environ, {'BEHIVE_API_KEY':'contract-test-only'}):
            with self.assertRaises(HTTPException):
                verify_auth(Request({'type':'http', 'headers':[]}))
            verify_auth(Request({'type':'http', 'headers':[(b'authorization', b'Bearer contract-test-only')]}))
        self.assertIn('BEHIVE_API_KEY', LANDING)


if __name__ == '__main__':
    unittest.main(verbosity=2)
