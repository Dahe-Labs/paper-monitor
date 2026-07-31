# Use explicit journal selection as the retrieval scope

Paper Monitor will use `journal_scope.selected_journals` as the sole current authority for journal-scoped retrieval, filtering, and Keyword Analysis. The former `top_n` mode is removed because it could rewrite a user's explicit selection and created a second definition of the same scope.

Older configurations remain readable: root-level `journals` is used only when `journal_scope.selected_journals` is absent, and existing `top_n` values are ignored and removed on the next settings save. Runtime Crossref `journal_titles`, RSS feed selection, and optional source enablement are derived from the explicit selection instead of overriding it. An explicitly empty selection means no journals and disables formal-journal retrieval; it never means an unrestricted query.

Keyword Analysis may narrow the configured formal-journal selection for one analysis run, but it cannot add journals outside Settings. The former 100/50-journal request caps are removed so the complete configured catalog can remain authoritative; date-span limits still bound analysis work.
