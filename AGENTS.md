# 作業ルール

- 配下の ZMK プロジェクトで作業する前に、[`shared-west-profiles` skill](skills/shared-west-profiles/SKILL.md) を読み、依存の互換性を確認した共有 West プロファイル内の worktree を使う。worktree と依存の扱いは skill に従う。
- この `zmk-workspace` リポジトリ自体への変更は、現在のチェックアウトに直接行う。検証が成功したら、すぐに変更を commit して現在のブランチを origin に push する。
- 一時的な調査メモやビルド結果（例: 日付付きの検証レポート）は `docs/local/` に保存する。このディレクトリは Git の追跡対象外とし、commit しない。
