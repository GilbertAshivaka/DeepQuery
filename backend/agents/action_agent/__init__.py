"""
Deep Query — Action Sub-Agent

The only unit that can cause external state change, and the most tightly controlled
(guide §5.2). Always preview → human approval → execute; one action per approval,
never batched. Importing this package registers it for Capability.ACTION.
"""

from agents.action_agent.agent import ActionAgent, action_agent

__all__ = ["ActionAgent", "action_agent"]
