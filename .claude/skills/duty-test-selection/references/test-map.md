# Focused test map

Confirm this map against the current `scripts/test_*.py` inventory before use.

| Change area | Primary focused tests |
| --- | --- |
| Login, role, session, identity | `scripts/test_login_auth.py`, `scripts/test_sidebar_ui.py` |
| Sidebar, routing, page registration | `scripts/test_sidebar_ui.py`, `scripts/test_master_and_views.py`, `scripts/test_screen_scaffold.py` |
| Shared screen scaffold or archetype | `scripts/test_screen_scaffold.py` plus each affected view contract |
| User master | `scripts/test_master_users_new.py`, `scripts/test_master_unified.py` |
| Organization master | `scripts/test_master_org.py`, `scripts/test_master_org_new.py`, `scripts/test_org_hierarchy_data.py`, `scripts/test_master_unified.py` |
| Work-type master | `scripts/test_master_work_types_new.py`, `scripts/test_master_unified.py` |
| Shared master lifecycle/forms | `scripts/test_master_common.py`, `scripts/test_master_forms.py`, `scripts/test_master_unified.py` |
| Schedule viewing/editing/saving | `scripts/test_schedule_contracts.py`, `scripts/test_schedule_save_units.py`, `scripts/test_assignment_linking.py` |
| Near-miss data and screens | `scripts/test_near_miss_data.py`, `scripts/test_near_miss_view.py` |
| Repository CRUD or cache | `scripts/test_supabase_crud.py`, `scripts/test_cache_invalidation.py` |
| Fail-closed reference counts | `scripts/test_reference_count_failclosed.py` |
| Migration or schema audit | Only the relevant `scripts/test_migration_*_audit.py`; this is evidence for current schema state, not a permanent product label |

For a shared module change, add every directly affected consumer's focused contract. Do not automatically run all tests solely because a shared file changed; trace actual imports and behavior first.
