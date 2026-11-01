"""
Star Trail Aligner - MCP Server Package.

Provides Model Context Protocol (MCP) tools, resources, and prompts for
discovering optimal alignment & synthesis settings and creating verified
star trail stacks.
"""

from mcp_server.diagnostics import (
    analyze_star_field_data,
    compare_alignment_candidates_data,
    evaluate_alignment_config,
    evaluate_stack_image,
    execute_stack_pipeline,
    filter_source_images,
    inspect_sequence_data,
    recommend_stack_settings,
    render_annotated_preview_image,
    render_preview_stack_data,
)
from mcp_server.server import create_mcp_server, main, mcp

__all__ = [
    "mcp",
    "create_mcp_server",
    "main",
    "filter_source_images",
    "inspect_sequence_data",
    "analyze_star_field_data",
    "evaluate_alignment_config",
    "compare_alignment_candidates_data",
    "recommend_stack_settings",
    "evaluate_stack_image",
    "render_annotated_preview_image",
    "execute_stack_pipeline",
    "render_preview_stack_data",
]
