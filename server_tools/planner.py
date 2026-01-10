"""
Planner Tools
=============

Sequential thinking and planning tools for structured problem-solving.
"""

import json
from typing import List, Dict, Any, Optional

from src.tools import Tool


class SequentialThinkingServer:
    """
    Stateful server for sequential thinking with plan tracking.
    """
    
    def __init__(self):
        self.thought_history: List[Dict[str, Any]] = []
        self.branches: Dict[str, List[Dict[str, Any]]] = {}
        self.goal_summary: str = ""
        self.current_plan: List[Dict[str, Any]] = []
        self.checkpoints: Dict[str, Dict[str, Any]] = {}
    
    def process_thought(self, **kwargs) -> str:
        """Process a thought and return the result."""
        thought = kwargs.get("thought", "")
        thought_number = kwargs.get("thoughtNumber", 1)
        total_thoughts = kwargs.get("totalThoughts", 1)
        next_thought_needed = kwargs.get("nextThoughtNeeded", True)
        goal_summary = kwargs.get("goalSummary")
        plan = kwargs.get("plan")
        updated_plan = kwargs.get("updatedPlan")
        completed_step = kwargs.get("completedStep")
        is_revision = kwargs.get("isRevision", False)
        revises_thought = kwargs.get("revisesThought")
        branch_from_thought = kwargs.get("branchFromThought")
        branch_id = kwargs.get("branchId")
        needs_more_thoughts = kwargs.get("needsMoreThoughts", False)
        
        # Update goal summary if provided in first thought
        if thought_number == 1 and goal_summary:
            self.goal_summary = goal_summary
        
        # Process plan if provided in first thought
        if thought_number == 1 and plan:
            self.current_plan = plan
        
        # Update plan if provided
        if updated_plan:
            self.current_plan = updated_plan
        
        # Adjust total thoughts if needed
        if thought_number > total_thoughts:
            total_thoughts = thought_number
        
        # Create thought data
        thought_data = {
            "thought": thought,
            "thoughtNumber": thought_number,
            "totalThoughts": total_thoughts,
            "nextThoughtNeeded": next_thought_needed,
            "isRevision": is_revision,
            "revisesThought": revises_thought,
            "branchFromThought": branch_from_thought,
            "branchId": branch_id,
            "needsMoreThoughts": needs_more_thoughts,
            "goalSummary": goal_summary,
            "completedStep": completed_step
        }
        
        # Store thought
        self.thought_history.append(thought_data)
        
        # Handle branching
        if branch_from_thought and branch_id:
            if branch_id not in self.branches:
                self.branches[branch_id] = []
            self.branches[branch_id].append(thought_data)
        
        # Get recent thoughts for context
        recent_thoughts = self.thought_history[-3:] if len(self.thought_history) > 3 else self.thought_history
        
        # Build response
        result = {
            "thoughtNumber": thought_number,
            "totalThoughts": total_thoughts,
            "nextThoughtNeeded": next_thought_needed,
            "branches": list(self.branches.keys()),
            "thoughtHistoryLength": len(self.thought_history),
            "goalSummary": self.goal_summary,
            "currentPlan": self.current_plan,
            "completedStep": completed_step,
            "previousThoughts": recent_thoughts,
            "thoughtHistory": [
                {
                    "thought": t["thought"],
                    "thoughtNumber": t["thoughtNumber"],
                    "isRevision": t.get("isRevision"),
                    "branchId": t.get("branchId"),
                    "completedStep": t.get("completedStep")
                }
                for t in self.thought_history
            ]
        }
        
        return json.dumps(result, indent=2)
    
    def save_checkpoint(self, checkpointId: Optional[str] = None) -> str:
        """Save the current state to a checkpoint."""
        checkpoint_id = checkpointId or f"checkpoint_{len(self.checkpoints)}"
        
        self.checkpoints[checkpoint_id] = {
            "thoughtHistory": list(self.thought_history),
            "branches": dict(self.branches),
            "goalSummary": self.goal_summary,
            "currentPlan": list(self.current_plan)
        }
        
        return json.dumps({
            "result": f"Checkpoint {checkpoint_id} saved successfully",
            "checkpointId": checkpoint_id
        }, indent=2)
    
    def load_checkpoint(self, checkpointId: str) -> str:
        """Load a checkpoint."""
        if checkpointId not in self.checkpoints:
            return json.dumps({
                "error": f"Checkpoint {checkpointId} not found"
            }, indent=2)
        
        checkpoint = self.checkpoints[checkpointId]
        self.thought_history = list(checkpoint["thoughtHistory"])
        self.branches = dict(checkpoint["branches"])
        self.goal_summary = checkpoint["goalSummary"]
        self.current_plan = list(checkpoint["currentPlan"])
        
        return json.dumps({
            "result": f"Checkpoint {checkpointId} loaded successfully",
            "thoughtHistory": [
                {"thought": t["thought"], "thoughtNumber": t["thoughtNumber"]}
                for t in self.thought_history
            ],
            "branches": list(self.branches.keys()),
            "goalSummary": self.goal_summary
        }, indent=2)


# Global instance for stateful thinking
_thinking_server = SequentialThinkingServer()


class PlannerTools:
    """
    Planner tool provider with sequential thinking tools.
    
    Usage:
        planner_tools = PlannerTools()
        all_tools = other_tools + planner_tools.tools
    """
    
    def __init__(self):
        """Initialize planner tools."""
        self.tools = self._create_tools()
    
    def _create_tools(self) -> List[Tool]:
        """Create the planner tools."""
        
        sequential_thinking_tool = Tool(
            name="sequentialthinking",
            description="""A detailed tool for dynamic and reflective problem-solving through thoughts.
This tool helps analyze problems through a flexible thinking process that can adapt and evolve.
Each thought can build on, question, or revise previous insights as understanding deepens.

When to use this tool:
- Breaking down complex problems into steps
- Planning and design with room for revision
- Analysis that might need course correction
- Problems where the full scope might not be clear initially
- Problems that require a multi-step solution
- Tasks that need to maintain context over multiple steps

Key features:
- Provide a goalSummary in your first thought to maintain focus
- Create a detailed plan of tasks with nested subtasks
- Each thought should correspond to at most one plan item completion
- You can adjust totalThoughts up or down as you progress
- You can question or revise previous thoughts
- You can branch or backtrack as needed

You should:
1. Begin with a clear goalSummary and detailed plan in your first thought
2. Each thought should correspond to at most one completed task
3. Update the plan in subsequent thoughts to mark progress
4. Only set nextThoughtNeeded to false when truly done""",
            parameters={
                "type": "object",
                "properties": {
                    "thought": {
                        "type": "string",
                        "description": "Your current thinking step"
                    },
                    "goalSummary": {
                        "type": "string",
                        "description": "A concise description of what you're trying to accomplish (include in first thought)"
                    },
                    "plan": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "completed": {"type": "string", "enum": ["true", "false", "in progress"]}
                            },
                            "required": ["text", "completed"]
                        },
                        "description": "Initial plan with tasks (include in first thought)"
                    },
                    "updatedPlan": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "completed": {"type": "string", "enum": ["true", "false", "in progress"]}
                            },
                            "required": ["text", "completed"]
                        },
                        "description": "Updated plan with progress marked"
                    },
                    "completedStep": {
                        "type": "string",
                        "description": "The plan item text that was completed in this thought"
                    },
                    "nextThoughtNeeded": {
                        "type": "boolean",
                        "description": "Whether another thought step is needed"
                    },
                    "thoughtNumber": {
                        "type": "integer",
                        "description": "Current thought number",
                        "minimum": 1
                    },
                    "totalThoughts": {
                        "type": "integer",
                        "description": "Estimated total thoughts needed",
                        "minimum": 1
                    },
                    "isRevision": {
                        "type": "boolean",
                        "description": "Whether this revises previous thinking"
                    },
                    "revisesThought": {
                        "type": "integer",
                        "description": "Which thought is being reconsidered"
                    },
                    "branchFromThought": {
                        "type": "integer",
                        "description": "Branching point thought number"
                    },
                    "branchId": {
                        "type": "string",
                        "description": "Branch identifier"
                    },
                    "needsMoreThoughts": {
                        "type": "boolean",
                        "description": "If more thoughts are needed"
                    }
                },
                "required": ["thought", "nextThoughtNeeded", "thoughtNumber", "totalThoughts"]
            },
            handler=_thinking_server.process_thought
        )
        
        save_checkpoint_tool = Tool(
            name="saveThoughtCheckpoint",
            description="Save the current thinking state to a checkpoint for later retrieval",
            parameters={
                "type": "object",
                "properties": {
                    "checkpointId": {
                        "type": "string",
                        "description": "Identifier for the checkpoint (optional)"
                    }
                }
            },
            handler=_thinking_server.save_checkpoint
        )
        
        load_checkpoint_tool = Tool(
            name="loadThoughtCheckpoint",
            description="Load a previously saved thinking state from a checkpoint",
            parameters={
                "type": "object",
                "properties": {
                    "checkpointId": {
                        "type": "string",
                        "description": "Identifier for the checkpoint to load"
                    }
                },
                "required": ["checkpointId"]
            },
            handler=_thinking_server.load_checkpoint
        )
        
        return [sequential_thinking_tool, save_checkpoint_tool, load_checkpoint_tool]
