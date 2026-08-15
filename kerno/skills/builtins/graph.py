# kerno/skills/builtins/graph.py
"""
Built-in graph and network skills.

This complements ``network.py`` with concise graph construction and
centrality helpers used by examples and analytical workflows.
"""

_GRAPH_SKILLS_CODE = r'''
import pandas as pd
from IPython.display import display as _display


def build_graph(edges: pd.DataFrame, source_col: str, target_col: str,
                weight_col: str = None, directed: bool = False):
    """Build a NetworkX graph from an edge list."""
    try:
        import networkx as nx
    except ImportError as exc:
        raise ImportError("networkx is required. Install with: pip install networkx") from exc

    G = nx.from_pandas_edgelist(
        edges,
        source=source_col,
        target=target_col,
        edge_attr=weight_col,
        create_using=nx.DiGraph if directed else nx.Graph(),
    )
    print(f"✓ Graph built: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
    return G


def graph_centrality(G, top_n: int = 10) -> pd.DataFrame:
    """Return degree, PageRank, and betweenness centrality."""
    import networkx as nx

    df = pd.DataFrame({
        "degree": dict(G.degree(weight="weight")),
        "pagerank": nx.pagerank(G, weight="weight"),
        "betweenness": nx.betweenness_centrality(G, weight="weight"),
    }).sort_values("pagerank", ascending=False)
    _display(df.head(top_n))
    return df


def draw_graph(G, layout: str = "spring") -> None:
    """Draw a NetworkX graph using a spring or Kamada-Kawai layout."""
    import networkx as nx
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    pos = nx.kamada_kawai_layout(G) if layout == "kamada_kawai" else nx.spring_layout(G, seed=42)
    degrees = dict(G.degree())
    fig, ax = plt.subplots(figsize=(10, 8))
    nx.draw(
        G, pos, ax=ax,
        node_size=[max(50, degrees.get(n, 0) * 20) for n in G.nodes()],
        node_color="#009E73", edge_color="#BBBBBB", with_labels=False, alpha=0.8,
    )
    ax.set_title("Graph")
    fig.tight_layout()
    _display(fig)
    plt.close(fig)
'''


def get_code() -> str:
    return _GRAPH_SKILLS_CODE
