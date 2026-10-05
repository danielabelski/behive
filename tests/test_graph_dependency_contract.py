"""Dependency contract: graph feature must not rely on harvest transitives."""
from pathlib import Path
import tomllib


def test_graph_dependency_has_declared_install_extra():
    project = tomllib.loads((Path(__file__).parents[1] / 'pyproject.toml').read_text())['project']
    extras = project['optional-dependencies']
    for dependency in ('networkx', 'numpy', 'rapidfuzz'):
        assert any(dep.startswith(dependency + '>=') for dep in extras.get('graph', []))
    assert 'graph' in ','.join(extras['all'])
