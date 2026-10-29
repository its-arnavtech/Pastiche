---
id: T-024
title: Tenant and track deletion removes derived recipes and renders
status: todo
owner: opus-cc
branch: feature/recipe-deletion
lane: none
depends_on: [T-021, T-023]
owns_paths: [src/remixer/adapters/, src/remixer/interfaces.py]
claimed_at:
heartbeat_at:
priority: P2
---

## Goal

Deleting a tenant, or a track (song) within a tenant, must remove or tombstone every recipe whose provenance contains it, found via Lineage.containing(song=...) including superseded versions (heads_only=False), plus lineage rows and every render of those recipes. Deleting a tenant removes all its recipes. Other tenants and unrelated recipes are untouched. Spec POC 2 section 4. Expose as Catalog methods, e.g. delete_track(tenant, song_id) -> DeletionReport(recipes_removed, renders_removed) and delete_tenant(tenant).

## Definition of done

Contract test: after deleting a song, get() of every recipe that used it raises KeyError, containing(song=...) is empty, renders are gone, other recipes and tenants are byte-identical.

## Progress and handoff log

- 2026-10-29T04:13:23Z cursor-opus: created
