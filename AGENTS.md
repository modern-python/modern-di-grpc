# AGENTS.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`modern-di-grpc` is a gRPC (`grpcio`) integration for
[`modern-di`](https://github.com/modern-python/modern-di); [`CONTEXT.md`](CONTEXT.md) opens with what
it does and owns the vocabulary — read it before naming a concept in code, a test name, or an issue
title. It is one of that project's integrations, each of which lives in a separate repository and
ships as a separate PyPI package.

## Commands

`just` (task runner) and `uv` (package manager). The [`justfile`](justfile) is the source of truth —
`just --list`, or read it; every non-obvious recipe carries its intent as a comment.

## Architecture

All implementation is `modern_di_grpc/main.py`, short enough to read whole. Read it.

## Workflow

Real work **not scheduled** becomes a GitHub issue.

An invariant is a test whose name is the claim, with a docstring opening `INVARIANT:` and a second
paragraph naming **what breaks it** — design rationale, not a report of what this one test catches.
Nothing enforces that docstring shape; it is read at review time.
