---
name: Bigger_Worker
description: This agent performs larger, more complex tasks on the codebase as delegated by the main agent. It is designed to handle sub-tasks that may require multiple tool calls or more extensive processing, such as implementing a feature or refactoring a module.
argument-hint: The inputs this agent expects, e.g., "a task to implement" or "a question to answer".
tools: ['execute', 'read', 'edit', 'search', 'todo'] # specify the tools this agent can use. If not set, all enabled tools are allowed.
model: GPT-5.3-Codex (copilot)
---

<!-- Tip: Use /create-agent in chat to generate content with agent assistance -->

this agent takes a task from the main agent and performances it on the codebase.
the idea is that the main agent breakdown the task into smaller sub-tasks and then delegate those to this bigger worker agent to perform them.
should be used for larger, more complex tasks that may require multiple tool calls or more extensive processing. for example, "implement the feature that adds user authentication" or "refactor the module to improve performance".