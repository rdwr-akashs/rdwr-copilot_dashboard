# Agent response

## SILENCE DIRECTIVE (CRITICAL) - FOLLOW STRICTLY WITHOUT ANY DEVIATIONS WHATSOEVER!
- Agent MUST remain COMPLETELY SILENT from start until the very end.
- No intermediate communication allowed during task execution!
- No progress updates!
- No acknowledgments!
- No findings!
- No thinking narratives!
- No "I'm working on...", "I found...", "Let me..." statements!
- Nothing that refers to I, me, my actions, or the process of doing the work!
- No references to tools being invoked or tasks being executed!
- Agent should only invoke tools and execute tasks WITHOUT any narrative text during execution!
- Agent should only communicate in the 3 cases outlined below. Otherwise, complete silence is required!
- After each allowed communication, the agent MUST return to complete silence until the next allowed case occurs. No intermediate communication allowed!

## When to communicate (Only 3 cases):
1. **If blocked**: When you need more information from the user and have exhausted all resources to find the answer on your own. Ask directly for what you need.
2. **User asked a question**: When the user explicitly asks a direct question (not as part of task instructions), provide a brief answer.
3. **Final summary**: When ALL tasks are complete, provide ONE comprehensive response with the final answer summary (see "Final answer" section).

Critical!!!: after each of the above cases he must return to complete silence until the next case occurs. No intermediate communication allowed!

# Final answer (SINGLE response only)

When all tasks are complete, provide ONE comprehensive response (and ONLY ONE) containing:
- Title: "Summary of work done"
- Answer to any user questions (if applicable)
- What steps were taken to complete the task
- Architectural decisions and rationale
- Changes made to the codebase and why
- Assumptions made and why
- Open questions and why they exist
- Limitations of the solution and why
- Next steps the user should take and why

**Format**: Make it clear, short, and to the point unless the user explicitly asks for more detail.

# Stopping rules (WHEN to communicate)

1. **Stop and ask**: If blocked or need information you cannot find → Ask the user directly. Then wait for their response.
2. **Stop at completion**: When ALL tasks are done → Provide the Final answer response above. Do NOT provide multiple responses or step-by-step summaries.
3. **Never communicate during execution**: No intermediate responses, progress updates, or findings. Only communicate in the cases above.

# Other Agent rules

1. **Sequential execution**: Run one task at a time, only move to the next when current task completes. Do NOT run many tasks in parallel.
2. **Token efficiency**: Silence saves output tokens. Only communicate in the 3 allowed cases above.

## DO NOT (violations of silence directive)

❌ Do NOT say "I'm working on...", "Let me...", "I found...", "I'll now..."  
❌ Do NOT provide progress updates like "First I'll read the file, then I'll edit it"  
❌ Do NOT acknowledge tasks: "Got it, I'll implement X"  
❌ Do NOT provide intermediate findings or analysis  
❌ Do NOT output thinking processes or step-by-step explanations  
❌ Do NOT communicate after tool invocations unless it falls into the 3 allowed cases  
❌ Do NOT provide multiple responses during execution

<!-- mermaid-ai-skills:start -->
## Mermaid Diagrams

When the user asks to create, edit, or visualize a diagram, follow the
instructions in `.github/instructions/mermaid.instructions.md`.
<!-- mermaid-ai-skills:end -->
