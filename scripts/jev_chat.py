#!/usr/bin/env python3
"""
Interactive JEV (Judgment and Evaluation) chat tool for opencode.
Provides a simple REPL interface to test JEV decision making.
"""

import json
import subprocess
import sys

JEV_TOOL_PATH = "/Users/aryanagarwal/munder-difflin-new/hive/agents/jev/bin/jev_decision_tool.py"

def run_jev(decision_type, context=None, **kwargs):
    """Run the JEV decision tool with given parameters."""
    if context is None:
        context = {}
    
    request = {
        "decision_type": decision_type,
        "context": context,
        **kwargs
    }
    
    try:
        result = subprocess.run(
            ['python3', JEV_TOOL_PATH],
            input=json.dumps(request),
            text=True,
            capture_output=True
        )
        
        if result.returncode != 0:
            return {"success": False, "error": f"JEV tool failed: {result.stderr}"}
        
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        return {"success": False, "error": f"Failed to parse JEV output: {e}"}
    except Exception as e:
        return {"success": False, "error": f"Error running JEV: {e}"}

def main():
    print("=== JEV (Judgment and Evaluation) Interactive Chat ===")
    print("Type 'help' for commands, 'quit' to exit")
    print()
    
    while True:
        try:
            command = input("jev> ").strip()
            
            if not command:
                continue
                
            if command.lower() in ['quit', 'exit']:
                print("Goodbye!")
                break
                
            if command.lower() == 'help':
                print("""
Available commands:
  help - Show this help
  choice - Make a choice decision (requires options)
  score - Score an agent/task (requires agent and task)
  noul - Get a NOUL decision (requires agent and task)
  quit/exit - Exit the chat
                """)
                continue
            
            if command.lower() == 'choice':
                print("\n--- Choice Decision ---")
                options_input = input("Enter options (comma-separated): ").strip()
                if not options_input:
                    print("Error: Options required")
                    continue
                options = [opt.strip() for opt in options_input.split(',') if opt.strip()]
                if len(options) < 2:
                    print("Error: Need at least 2 options")
                    continue
                
                context_input = input("Enter context (JSON, or empty for {}): ").strip()
                context = {}
                if context_input:
                    try:
                        context = json.loads(context_input)
                    except json.JSONDecodeError:
                        print("Warning: Invalid JSON, using empty context")
                        context = {}
                
                result = run_jev("choice", context=context, options=options)
                print(f"Result: {json.dumps(result, indent=2)}")
                print()
                
            elif command.lower() == 'score':
                print("\n--- Score Decision ---")
                agent = input("Enter agent ID: ").strip()
                if not agent:
                    print("Error: Agent ID required")
                    continue
                task = input("Enter task ID: ").strip()
                if not task:
                    print("Error: Task ID required")
                    continue
                
                context_input = input("Enter context (JSON, or empty for {}): ").strip()
                context = {}
                if context_input:
                    try:
                        context = json.loads(context_input)
                    except json.JSONDecodeError:
                        print("Warning: Invalid JSON, using empty context")
                        context = {}
                
                result = run_jev("score", context=context, agent=agent, task=task)
                print(f"Result: {json.dumps(result, indent=2)}")
                print()
                
            elif command.lower() == 'noul':
                print("\n--- NOUL Decision ---")
                agent = input("Enter agent ID: ").strip()
                if not agent:
                    print("Error: Agent ID required")
                    continue
                task = input("Enter task ID: ").strip()
                if not task:
                    print("Error: Task ID required")
                    continue
                
                context_input = input("Enter context (JSON, or empty for {}): ").strip()
                context = {}
                if context_input:
                    try:
                        context = json.loads(context_input)
                    except json.JSONDecodeError:
                        print("Warning: Invalid JSON, using empty context")
                        context = {}
                
                result = run_jev("noul", context=context, agent=agent, task=task)
                print(f"Result: {json.dumps(result, indent=2)}")
                print()
                
            else:
                print(f"Unknown command: {command}")
                print("Type 'help' for available commands")
                
        except KeyboardInterrupt:
            print("\nUse 'quit' to exit")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    main()