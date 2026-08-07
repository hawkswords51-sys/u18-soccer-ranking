import pro_signings as ps
m = ps.badges_by_team_id()
bad = []
for tid in m:
    try:
        h = ps.render_team_badge_html(tid, m)
        assert h and 'ps-badge' in h
    except Exception as e:
        bad.append((tid, e))
print('バッジ生成テスト:', len(m), 'チーム / エラー:', bad or 'なし')
print('未知IDは空文字:', ps.render_team_badge_html('no-such-team', m) == '')
both = [t for t, v in m.items() if v['naitei'] and v['pro']]
print('内定・プロ契約が併存するチーム:', both or 'なし')
