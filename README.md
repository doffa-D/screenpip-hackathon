# Melon — memory to action

**Your computer already remembers what you do. Melon turns that memory into action.**

## The idea

A lot of our day is the same work done again and again: sending the same kind of email, filling the same
sheet, exporting the same report. We have already done these tasks once, but we still repeat every click.

Melon looks at what you did before, understands the task, and does it again for you, with you in control.

## How it works

1. **Remember.** A local recorder ([Screenpipe](https://github.com/mediar-ai/screenpipe)) keeps a record of what happened on your screen.
2. **Find.** Ask in plain words ("find the emails I sent today"), or let Melon spot the tasks you keep repeating.
3. **Understand.** Melon rebuilds a past task as a clear workflow: the steps, the values you used, and the evidence it came from. You can read it and edit it.
4. **Repeat.** An AI agent carries out the workflow on your desktop, one step at a time.
5. **Stay in control.** You review a workflow before it runs, approve its actions, and can stop it at any moment. After each change, Melon checks that it really worked.

## Night shift

While you are away, Melon can notice the step you usually do next but forgot, and prepare it for you.
It only works inside a scope you approved, and by default it prepares things without sending or deleting anything.
In the morning it tells you what it noticed, what it did, and what it left for you.

## Principles

- **You decide.** Nothing runs without your review and approval.
- **No guessing.** If information is missing, Melon asks instead of inventing it.
- **Verify, don't assume.** A task is only done when Melon has checked the result on screen.
- **Local first.** The app runs on your own computer. The history it needs is sent only to the AI provider you choose.

*A hackathon project.*
