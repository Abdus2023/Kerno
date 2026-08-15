# kerno/skills/builtins/network.py
"""
Built-in graph and network analysis skills.

NetworkX is imported lazily: sessions that do not analyze graphs do not pay
the import cost and do not require it to be installed.
"""

_NETWORK_SKILLS_CODE = r'''
import pandas as pd
from IPython.display import display as _display


def build_network(edges: pd.DataFrame, source: str, target: str,
                  weight: str = None, directed: bool = False):
    """
    Build a NetworkX graph from an edge-list DataFrame.
    """
    try:
        import networkx as nx
    except ImportError as exc:
        raise ImportError("networkx is required. Install with: pip install networkx") from exc

    graph_cls = nx.DiGraph if directed else nx.Graph
    G = nx.from_pandas_edgelist(
        edges,
        source=source,
        target=target,
        edge_attr=weight,
        create_using=graph_cls(),
    )
    print(f"✓ Built network: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
    print(f"  Density: {nx.density(G):.4f}")
    return G


def analyze_network(G, top_n: int = 10) -> pd.DataFrame:
    """
    Compute degree, PageRank, betweenness, and optional community labels.

    Returns a sorted centrality DataFrame.
    """
    import networkx as nx

    metrics = pd.DataFrame({
        "degree": dict(G.degree()),
        "in_degree": dict(G.in_degree()) if G.is_directed() else dict(G.degree()),
        "out_degree": dict(G.out_degree()) if G.is_directed() else dict(G.degree()),
        "pagerank": nx.pagerank(G),
        "betweenness": nx.betweenness_centrality(G),
    }).sort_values("pagerank", ascending=False)

    if not G.is_directed():
        try:
            from networkx.algorithms.community import greedy_modularity_communities
            communities = list(greedy_modularity_communities(G))
            community_by_node = {}
            for i, community in enumerate(communities):
                for node in community:
                    community_by_node[node] = i
            metrics["community"] = metrics.index.map(community_by_node)
        except Exception as exc:
            print(f"⚠️  Community detection skipped: {exc}")

    _display(metrics.head(top_n))
    return metrics


def find_influencers(G, top_n: int = 10) -> pd.DataFrame:
    """Identify influential nodes by centrality metrics."""
    return analyze_network(G, top_n=top_n)


def plot_network(G, layout: str = "spring", node_size_scale: int = 20) -> None:
    """Render the network with nodes sized by degree."""
    import networkx as nx
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if layout == "kamada_kawai":
        pos = nx.kamada_kawai_layout(G)
    else:
        pos = nx.spring_layout(G, seed=42)

    degrees = dict(G.degree())
    sizes = [max(50, degrees.get(node, 0) * node_size_scale) for node in G.nodes()]

    fig, ax = plt.subplots(figsize=(10, 8))
    nx.draw(
        G, pos, ax=ax, node_size=sizes, node_color="#56B4E9",
        edge_color="#999999", alpha=0.7, with_labels=False,
    )
    ax.set_title(f"Network Graph ({G.number_of_nodes()} nodes)")
    fig.tight_layout()
    _display(fig)
    plt.close(fig)
'''


def get_code() -> str:
    return _NETWORK_SKILLS_CODE
