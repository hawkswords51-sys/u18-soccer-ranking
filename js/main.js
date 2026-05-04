// メインアプリケーション
// ============================================================
// P1-3: リーグ内順位は `leagueRank` 優先、旧データ互換で `rank` フォールバック
// P2  : プレミア / プリンスのリーグ順位表を階層アコーディオン化
//        *** option (A): 排他的アコーディオン (一度に1つだけ開く) ***
//        同じ name を共有する <details> は同時に1つしか開かない
// ============================================================
class SoccerApp {
    constructor() {
        this.map = null;
        this.currentPrefecture = null;
        this.tournamentData = null;   // data/tournaments.json を保持
        this.init();
    }

    async init() {
        console.log('SoccerApp initialization started');

        this.map = new RegionListGenerator('japanMap');
        await this.map.generate();
        console.log('Region list generated');

        // 大会成績データ (data/tournaments.json) を読み込み
        await this.loadTournamentData();
        console.log('Tournament data loaded');

        this.setupEventListeners();
        console.log('Event listeners setup completed');

        this.setupSearch();
        console.log('Search functionality initialized');

        // バッジ用カスタムツールチップ (HTMLネイティブの title より素早く表示)
        this.setupTournamentTooltip();
        console.log('Tournament tooltip handler ready');
    }

    // ============================================================
    // バッジ用カスタムツールチップ
    // - 表示遅延を 120ms に短縮 (ネイティブ title は ~500ms)
    // - position: fixed で表内 overflow に阻まれない
    // - data-tooltip 属性の改行 (\n) を保持
    // ============================================================
    setupTournamentTooltip() {
        let tipEl   = null;
        let timer   = null;
        let current = null;

        const ensureTip = () => {
            if (tipEl) return tipEl;
            tipEl = document.createElement('div');
            tipEl.className = 'tournament-tooltip';
            tipEl.setAttribute('role', 'tooltip');
            document.body.appendChild(tipEl);
            return tipEl;
        };

        const showTip = (target) => {
            const text = target.getAttribute('data-tooltip');
            if (!text) return;
            const tip = ensureTip();
            tip.textContent = text;
            tip.style.visibility = 'hidden';
            tip.style.display = 'block';
            tip.style.left = '0px';
            tip.style.top  = '0px';
            // 一度描画させて寸法取得
            const r  = target.getBoundingClientRect();
            const tr = tip.getBoundingClientRect();
            const margin = 8;
            // 右側に出すのが基本、画面外なら左
            let left = r.right + margin;
            if (left + tr.width > window.innerWidth - 4) {
                left = r.left - tr.width - margin;
            }
            if (left < 4) left = 4;
            // 縦は中央寄せ、画面外調整
            let top = r.top + (r.height / 2) - (tr.height / 2);
            if (top < 4) top = 4;
            if (top + tr.height > window.innerHeight - 4) {
                top = window.innerHeight - tr.height - 4;
            }
            tip.style.left = `${left}px`;
            tip.style.top  = `${top}px`;
            tip.style.visibility = 'visible';
        };

        const hideTip = () => {
            if (timer) { clearTimeout(timer); timer = null; }
            if (tipEl) tipEl.style.display = 'none';
            current = null;
        };

        // mouseover はバブリングするので document に1個だけ設置
        document.addEventListener('mouseover', (e) => {
            const icon = e.target.closest && e.target.closest('.team-tournament-icon');
            if (!icon || icon === current) return;
            current = icon;
            if (timer) clearTimeout(timer);
            timer = setTimeout(() => showTip(icon), 120);
        });

        document.addEventListener('mouseout', (e) => {
            const icon = e.target.closest && e.target.closest('.team-tournament-icon');
            if (!icon) return;
            // 関連先がまだバッジ内なら維持
            const to = e.relatedTarget;
            if (to && to.closest && to.closest('.team-tournament-icon') === icon) return;
            hideTip();
        });

        // スクロール/クリックで隠す
        window.addEventListener('scroll', hideTip, true);
        window.addEventListener('resize', hideTip);
        document.addEventListener('click', hideTip);
    }

    // ============================================================
    // tournaments.json (4大会 × 直近5年の上位8チーム) の読み込み
    // build_tournaments.py が data/tournaments_data.yml から生成
    // ============================================================
    async loadTournamentData() {
        try {
            const response = await fetch('data/tournaments.json?_=' + Date.now());
            this.tournamentData = await response.json();
            // チーム名 → 直近5年の成績配列 のルックアップを構築
            this.tournamentLookup = this.buildTournamentLookup();
        } catch (e) {
            console.error('tournaments.json の読み込みに失敗:', e);
            this.tournamentData = null;
            this.tournamentLookup = {};
        }
    }

    // チーム名で大会成績を引けるようにフラットなルックアップを構築
    // (NFKC正規化 + 空白除去でゆるく一致)
    buildTournamentLookup() {
        const lookup = {};
        if (!this.tournamentData || !this.tournamentData.tournaments) return lookup;
        for (const tdata of Object.values(this.tournamentData.tournaments)) {
            if (!tdata || !tdata.results) continue;
            const tournamentLabel = tdata.shortName || tdata.displayName || '';
            for (const [year, yearData] of Object.entries(tdata.results)) {
                for (const t of (yearData.teams || [])) {
                    const key = this.normalizeTeamName(t.team);
                    if (!key) continue;
                    if (!lookup[key]) lookup[key] = [];
                    lookup[key].push({
                        year:       year,
                        tournament: tournamentLabel,
                        result:     t.result,
                        rank:       t.rank
                    });
                }
            }
        }
        return lookup;
    }

    normalizeTeamName(name) {
        if (!name) return '';
        return String(name).normalize('NFKC').replace(/[\s\u3000]/g, '');
    }

    // チーム名から大会バッジ HTML を生成 (該当なしなら空文字)
    // 直近5年の中で最も成績が良い1件のバッジを表示し、
    // ホバーで全成績がツールチップで見える
    getTournamentBadge(teamName) {
        if (!this.tournamentLookup) return '';
        const key = this.normalizeTeamName(teamName);
        const results = this.tournamentLookup[key];
        if (!results || results.length === 0) return '';

        // 最高成績 (rank が小さいほど上位)
        const best = results.reduce((a, b) => {
            const ra = (a.rank == null ? 99 : a.rank);
            const rb = (b.rank == null ? 99 : b.rank);
            return ra <= rb ? a : b;
        });
        const badgeClass = this.resultBadgeClass(best.result);

        // ツールチップ: 年度 (新→旧) でソート
        const sorted = [...results].sort((a, b) => Number(b.year) - Number(a.year));
        const tooltipText = sorted
            .map(r => `${r.year} ${r.tournament} ${r.result}`)
            .join('\n');

        // 文字なしの小さな丸ドット (色だけで区別)
        // ※ title 属性ではなく data-tooltip を使い、カスタムツールチップで表示遅延を短くする
        return ` <span class="team-tournament-icon ${badgeClass}" data-tooltip="${this.escapeHtml(tooltipText)}" aria-label="${this.escapeHtml(best.result)}"></span>`;
    }

    setupEventListeners() {
        document.addEventListener('prefectureSelected', (e) => {
            console.log('prefectureSelected event received in main.js:', e.detail);
            this.showPrefectureDetail(e.detail.prefId, e.detail.prefName);
        });

        document.getElementById('closeModal').addEventListener('click', () => {
            this.closeModal();
        });

        document.getElementById('detailModal').addEventListener('click', (e) => {
            if (e.target.id === 'detailModal') {
                this.closeModal();
            }
        });

        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                this.switchTab(e.target.dataset.tab);
            });
        });

        document.getElementById('homeBtn').addEventListener('click', (e) => {
            e.preventDefault();
            this.showHome();
        });

        document.getElementById('searchBtn').addEventListener('click', (e) => {
            e.preventDefault();
            this.toggleSearch();
        });

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                this.closeModal();
            }
        });

        document.querySelectorAll('.info-card').forEach(card => {
            const iconDiv = card.querySelector('.info-icon');
            if (!iconDiv) return;
            if (iconDiv.classList.contains('premier')) {
                card.style.cursor = 'pointer';
                card.setAttribute('title', 'クリックしてプレミアリーグの順位表を表示');
                card.addEventListener('click', () => this.showLeagueGroup('premier'));
            } else if (iconDiv.classList.contains('prince')) {
                card.style.cursor = 'pointer';
                card.setAttribute('title', 'クリックしてプリンスリーグの順位表を表示');
                card.addEventListener('click', () => this.showLeagueGroup('prince'));
            }
        });
    }

    setupSearch() {
        const searchInput = document.getElementById('searchInput');
        const clearBtn = document.getElementById('clearSearchBtn');

        searchInput.addEventListener('input', (e) => {
            const query = e.target.value.trim();

            if (query) {
                clearBtn.style.display = 'block';
                this.performSearch(query);
            } else {
                clearBtn.style.display = 'none';
                this.clearSearchResults();
            }
        });

        clearBtn.addEventListener('click', () => {
            searchInput.value = '';
            clearBtn.style.display = 'none';
            this.clearSearchResults();
            searchInput.focus();
        });
    }

    performSearch(query) {
        const results = dataManager.searchTeams(query);
        this.displaySearchResults(results);
    }

    displaySearchResults(results) {
        const container = document.getElementById('searchResults');

        if (results.length === 0) {
            container.innerHTML = `
                <div class="search-no-results">
                    <i class="fas fa-search"></i>
                    <p>該当するチームが見つかりませんでした</p>
                </div>
            `;
            return;
        }

        const html = results.map(team => {
            const rankVal = (team.leagueRank != null ? team.leagueRank : team.rank);
            return `
            <div class="search-result-item" data-pref-id="${team.prefectureId}">
                <div class="search-result-team">${team.name}${this.getTournamentBadge(team.name)}</div>
                <div class="search-result-info">
                    <span><i class="fas fa-map-marker-alt"></i> ${team.prefectureName}</span>
                    <span><i class="fas fa-trophy"></i> ${team.league}</span>
                    <span><i class="fas fa-sort-numeric-down"></i> 順位: ${rankVal}位</span>
                </div>
            </div>
        `;
        }).join('');

        container.innerHTML = html;

        container.querySelectorAll('.search-result-item').forEach(item => {
            item.addEventListener('click', () => {
                const prefId = item.dataset.prefId;
                const pref = dataManager.getPrefecture(prefId);
                if (pref) {
                    this.showPrefectureDetail(prefId, pref.name);
                    this.showHome();
                }
            });
        });
    }

    clearSearchResults() {
        document.getElementById('searchResults').innerHTML = '';
    }

    toggleSearch() {
        const searchSection = document.getElementById('searchSection');
        const mapSection = document.getElementById('mapSection');

        if (searchSection.style.display === 'none') {
            searchSection.style.display = 'block';
            mapSection.style.display = 'none';
            document.getElementById('searchInput').focus();
        } else {
            searchSection.style.display = 'none';
            mapSection.style.display = 'block';
        }
    }

    showHome() {
        document.getElementById('searchSection').style.display = 'none';
        document.getElementById('mapSection').style.display = 'block';
        document.getElementById('searchInput').value = '';
        document.getElementById('clearSearchBtn').style.display = 'none';
        this.clearSearchResults();
    }

    showPrefectureDetail(prefId, prefName) {
        this.currentPrefecture = prefId;
        const pref = dataManager.getPrefecture(prefId);

        if (!pref || !pref.teams || pref.teams.length === 0) {
            alert(`この都道府県（${prefName}）のデータはまだ登録されていません。\nID: ${prefId}`);
            return;
        }

        const statsSummary = document.querySelector('.stats-summary');
        const tabsEl = document.querySelector('.tabs');
        if (statsSummary) statsSummary.style.display = '';
        if (tabsEl) tabsEl.style.display = '';

        document.getElementById('modalTitle').innerHTML = `
            <i class="fas fa-map-marker-alt"></i> ${prefName}
        `;

        document.getElementById('teamCount').textContent = pref.teams.length;
        document.getElementById('topLeague').textContent = this.getTopLeagueName(pref.teams);

        this.displayTeamsTable(pref.teams);
        // 旧: pref.championships (teams.json 内の手動データ)
        // 新: data/tournaments.json から prefId で抽出
        this.displayChampionshipsTable(prefId);

        this.switchTab('league');
        this.openModal();
    }

    getTopLeagueName(teams) {
        const hasPremiér = teams.some(t => t.league.includes('プレミアリーグ'));
        const hasPrince = teams.some(t => t.league.includes('プリンスリーグ'));

        if (hasPremiér) return 'プレミアリーグ';
        if (hasPrince) return 'プリンスリーグ';
        return '都道府県リーグ';
    }

    leagueTierPriority(league) {
        if (league.includes('プレミアリーグ')) return 0;
        if (league.includes('プリンスリーグ')) {
            if (league.includes('2部')) return 2;
            return 1;
        }
        return 3;
    }

    displayTeamsTable(teams) {
        const container = document.getElementById('teamsTable');

        // P1-3: 同一リーグ内は leagueRank 優先、旧データは rank にフォールバック
        const sortedTeams = [...teams].sort((a, b) => {
            const tierDiff = this.leagueTierPriority(a.league) - this.leagueTierPriority(b.league);
            if (tierDiff !== 0) return tierDiff;
            if (a.league === b.league) {
                const ra = (a.leagueRank != null ? a.leagueRank : a.rank);
                const rb = (b.leagueRank != null ? b.leagueRank : b.rank);
                return (ra || 99) - (rb || 99);
            }
            return (a.rank || 99) - (b.rank || 99);
        });

        const html = `
            <table class="data-table">
                <thead>
                    <tr>
                        <th>県内順位</th>
                        <th>チーム名</th>
                        <th>リーグ</th>
                        <th>順位</th>
                        <th>勝点</th>
                        <th>試合数</th>
                        <th>勝</th>
                        <th>分</th>
                        <th>負</th>
                        <th>得点</th>
                        <th>失点</th>
                        <th>得失差</th>
                    </tr>
                </thead>
                <tbody>
                    ${sortedTeams.map((team, index) => this.createTeamRow(team, index + 1)).join('')}
                </tbody>
            </table>
        `;

        container.innerHTML = html;
    }

    createTeamRow(team, prefRank) {
        const goalDiff = team.goalsFor - team.goalsAgainst;
        const rankClass = prefRank <= 3 ? `rank-${prefRank}` : 'rank-other';

        let leagueBadgeClass = 'prefecture';
        if (team.league.includes('プレミアリーグ')) {
            leagueBadgeClass = 'premier';
        } else if (team.league.includes('プリンスリーグ')) {
            leagueBadgeClass = 'prince';
        }

        // P1-3: 表示順位は leagueRank 優先
        const displayRank = (team.leagueRank != null ? team.leagueRank : team.rank);

        // ★ Phase 9-1g (2026-05): モバイルでバッジが折り返される際、
        // 「プレミアリーグ / EAST」「プリンスリーグ / 東北」「北海道リーグ / 1部」
        // のような自然な区切りで改行されるよう <wbr> (改行候補) を挿入
        const leagueDisplay = team.league
            .replace(/(プレミアリーグ|プリンスリーグ)/, '$1<wbr>')
            .replace(/(リーグ)(\d)/, '$1<wbr>$2');

        // ★ Phase 9-1h (2026-05): チーム名内の「U-18」「U18」が
        // 「U-1 / 8」のように途中で割れないよう、Uの前で改行させる
        const teamNameDisplay = team.name.replace(/(U-?\d+)/g, '<wbr>$1');

        return `
            <tr>
                <td>
                    <span class="rank-badge ${rankClass}">${prefRank}</span>
                </td>
                <td><strong>${teamNameDisplay}</strong>${this.getTournamentBadge(team.name)}</td>
                <td>
                    <span class="league-badge ${leagueBadgeClass}">${leagueDisplay}</span>
                </td>
                <td>${displayRank}位</td>
                <td><strong>${team.points}</strong></td>
                <td>${team.played}</td>
                <td>${team.won}</td>
                <td>${team.drawn}</td>
                <td>${team.lost}</td>
                <td>${team.goalsFor}</td>
                <td>${team.goalsAgainst}</td>
                <td style="color: ${goalDiff > 0 ? '#28a745' : goalDiff < 0 ? '#dc3545' : '#666'}">
                    ${goalDiff > 0 ? '+' : ''}${goalDiff}
                </td>
            </tr>
        `;
    }

    // ============================================================
    // 都道府県ページの「大会成績」タブを描画
    // data/tournaments.json から prefId に該当するチームを抽出し、
    // 大会ごとにセクション化 (高校選手権 → インターハイ → クラブユース → Jユース)
    // ============================================================
    displayChampionshipsTable(prefId) {
        const container = document.getElementById('championshipsTable');

        if (!this.tournamentData || !this.tournamentData.tournaments) {
            container.innerHTML = `
                <div style="text-align: center; padding: 40px; color: #666;">
                    <i class="fas fa-spinner fa-spin" style="font-size: 2rem; opacity: 0.5; margin-bottom: 15px;"></i>
                    <p>大会成績データを読み込めませんでした</p>
                </div>
            `;
            return;
        }

        const tournaments = this.tournamentData.tournaments;
        // 表示順: 高校選手権 → インターハイ → クラブユース → Jユース
        const order = ['all_japan_highschool', 'interhigh', 'club_youth_u18', 'j_youth_cup'];

        const sections = [];
        for (const tid of order) {
            const tdata = tournaments[tid];
            if (!tdata || !tdata.results) continue;

            // この都道府県のチームが入っている年だけを抽出 (新しい年順)
            const yearRows = [];
            const years = Object.keys(tdata.results).sort((a, b) => Number(b) - Number(a));
            for (const year of years) {
                const matched = (tdata.results[year].teams || [])
                    .filter(t => t.pref === prefId);
                if (matched.length > 0) {
                    yearRows.push({ year, teams: matched });
                }
            }

            if (yearRows.length === 0) continue;
            sections.push(this.renderTournamentSection(tdata, yearRows));
        }

        if (sections.length === 0) {
            container.innerHTML = `
                <div style="text-align: center; padding: 40px; color: #666;">
                    <i class="fas fa-trophy" style="font-size: 3rem; opacity: 0.3; margin-bottom: 15px;"></i>
                    <p>直近5年間で4大会のベスト8以上に進出した実績はありません</p>
                    <p style="font-size: 0.85rem; margin-top: 8px;">
                        （高校選手権 / インターハイ / クラブユース / Jユース）
                    </p>
                </div>
            `;
            return;
        }

        container.innerHTML = `
            <div class="tournament-section-list">
                ${sections.join('')}
            </div>
            <p class="tournament-disclaimer">
                <i class="fas fa-info-circle"></i>
                直近5年（2021〜2025）のベスト8以上の成績を表示しています
            </p>
        `;
    }

    // 大会1つぶんのセクション (タイトル + 年ごとの行)
    renderTournamentSection(tdata, yearRows) {
        const rowsHtml = yearRows.map(({ year, teams }) => {
            const teamCells = teams.map(t => {
                const badgeClass = this.resultBadgeClass(t.result);
                return `
                    <span class="tournament-result-team">
                        <span class="tournament-result-team-name">${this.escapeHtml(t.team)}</span>
                        <span class="tournament-result-badge ${badgeClass}">${this.escapeHtml(t.result)}</span>
                    </span>
                `;
            }).join('');
            return `
                <li class="tournament-year-row">
                    <span class="tournament-year">${this.escapeHtml(String(year))}年</span>
                    <span class="tournament-teams">${teamCells}</span>
                </li>
            `;
        }).join('');

        return `
            <div class="tournament-section">
                <h3 class="tournament-section-title">
                    <i class="fas fa-trophy"></i>
                    ${this.escapeHtml(tdata.displayName || tdata.shortName || '大会')}
                </h3>
                <ul class="tournament-year-list">
                    ${rowsHtml}
                </ul>
            </div>
        `;
    }

    // 成績ラベル → CSS クラス名
    resultBadgeClass(result) {
        switch (result) {
            case '優勝':    return 'result-champion';
            case '準優勝':   return 'result-runner-up';
            case 'ベスト4': return 'result-best4';
            case 'ベスト8': return 'result-best8';
            case '代表':    return 'result-representative';
            default:        return 'result-other';
        }
    }

    switchTab(tabName) {
        document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
        const targetBtn = document.querySelector(`[data-tab="${tabName}"]`);
        if (targetBtn) targetBtn.classList.add('active');

        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        const targetContent = document.getElementById(`${tabName}Tab`);
        if (targetContent) targetContent.classList.add('active');
    }

    openModal() {
        const modal = document.getElementById('detailModal');
        modal.classList.add('active');
        document.body.style.overflow = 'hidden';
    }

    closeModal() {
        const modal = document.getElementById('detailModal');
        modal.classList.remove('active');
        document.body.style.overflow = 'auto';
    }

    // ============================================================
    // P2: プレミア / プリンス 全体順位表 (階層アコーディオン)
    // option (A): 排他的アコーディオン (同じ name を共有する <details> は1つだけ開く)
    // ============================================================

    async showLeagueGroup(type) {
        const title = type === 'premier' ? 'プレミアリーグ' : 'プリンスリーグ';
        const icon  = type === 'premier' ? 'trophy' : 'medal';
        const keyword = title;

        // teams.json から生データを直接取得 (realTeamsGenerator の上書きを回避)
        let rawData = null;
        try {
            const response = await fetch('data/teams.json?_=' + Date.now());
            rawData = await response.json();
        } catch (e) {
            console.error('teams.json の読み込みに失敗:', e);
        }

        // 対象リーグのチームを収集
        const allTeams = [];
        if (rawData) {
            Object.entries(rawData).forEach(([prefId, prefData]) => {
                if (prefId === '_meta') return;
                if (!prefData || !Array.isArray(prefData.teams)) return;
                prefData.teams.forEach(team => {
                    if (team.league && team.league.includes(keyword)) {
                        allTeams.push({
                            ...team,
                            prefectureId: prefId,
                            prefectureName: prefData.name
                        });
                    }
                });
            });
        }

        if (allTeams.length === 0) {
            alert(`${title}のデータがまだ登録されていません。\n自動更新を実行してからお試しください。`);
            return;
        }

        // リーグ名でグルーピング + リーグ内ソート (P1-3: leagueRank 優先)
        const groups = {};
        allTeams.forEach(team => {
            const key = team.league;
            if (!groups[key]) groups[key] = [];
            groups[key].push(team);
        });
        Object.values(groups).forEach(teams => {
            teams.sort((a, b) => {
                const ra = (a.leagueRank != null ? a.leagueRank : a.rank);
                const rb = (b.leagueRank != null ? b.leagueRank : b.rank);
                if ((ra || 99) !== (rb || 99)) return (ra || 99) - (rb || 99);
                if ((b.points || 0) !== (a.points || 0)) return (b.points || 0) - (a.points || 0);
                const gdA = (a.goalsFor || 0) - (a.goalsAgainst || 0);
                const gdB = (b.goalsFor || 0) - (b.goalsAgainst || 0);
                if (gdB !== gdA) return gdB - gdA;
                return (b.goalsFor || 0) - (a.goalsFor || 0);
            });
        });

        // モーダル表示準備
        this.currentPrefecture = null;
        document.getElementById('modalTitle').innerHTML = `
            <i class="fas fa-${icon}"></i> ${title} 順位表
        `;

        const statsSummary = document.querySelector('.stats-summary');
        const tabsEl = document.querySelector('.tabs');
        if (statsSummary) statsSummary.style.display = 'none';
        if (tabsEl) tabsEl.style.display = 'none';

        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        const leagueTab = document.getElementById('leagueTab');
        if (leagueTab) leagueTab.classList.add('active');

        // 階層構造の定義 + デフォルト展開
        const hierarchy   = type === 'premier' ? this.getPremierHierarchy() : this.getPrinceHierarchy();
        const defaultOpen = type === 'premier'
            ? { region: 'east' }
            : { region: 'kanto', division: 'div1' };

        // name グループ名 (排他アコーディオンを成立させる鍵)
        const regionName = `${type}-region`; // 地域レベルは type ごとに排他

        const container = document.getElementById('teamsTable');
        container.innerHTML = `
            <div class="league-accordion-root">
                ${hierarchy.map(item =>
                    this.renderAccordionItem(item, groups, defaultOpen, type, regionName)
                ).join('')}
            </div>
        `;

        const champContainer = document.getElementById('championshipsTable');
        if (champContainer) champContainer.innerHTML = '';

        this.openModal();
    }

    // --- プレミア: EAST / WEST ------------------------------------
    getPremierHierarchy() {
        return [
            { key: 'east', label: 'EAST', leagueName: 'プレミアリーグEAST' },
            { key: 'west', label: 'WEST', leagueName: 'プレミアリーグWEST' }
        ];
    }

    // --- プリンス: 9地域 (一部は 1部/2部 にネスト) ---------------
    getPrinceHierarchy() {
        return [
            { key: 'hokkaido',     label: '北海道',   leagueName: 'プリンスリーグ北海道' },
            { key: 'tohoku',       label: '東北',     leagueName: 'プリンスリーグ東北' },
            { key: 'kanto',        label: '関東',     divisions: [
                { key: 'div1', label: '1部', leagueName: 'プリンスリーグ関東1部' },
                { key: 'div2', label: '2部', leagueName: 'プリンスリーグ関東2部' }
            ]},
            { key: 'hokushinetsu', label: '北信越',   divisions: [
                { key: 'div1', label: '1部', leagueName: 'プリンスリーグ北信越1部' },
                { key: 'div2', label: '2部', leagueName: 'プリンスリーグ北信越2部' }
            ]},
            { key: 'tokai',        label: '東海',     leagueName: 'プリンスリーグ東海' },
            { key: 'kansai',       label: '関西',     divisions: [
                { key: 'div1', label: '1部', leagueName: 'プリンスリーグ関西1部' },
                { key: 'div2', label: '2部', leagueName: 'プリンスリーグ関西2部' }
            ]},
            { key: 'chugoku',      label: '中国',     leagueName: 'プリンスリーグ中国' },
            { key: 'shikoku',      label: '四国',     leagueName: 'プリンスリーグ四国' },
            { key: 'kyushu',       label: '九州',     divisions: [
                { key: 'div1', label: '1部', leagueName: 'プリンスリーグ九州1部' },
                { key: 'div2', label: '2部', leagueName: 'プリンスリーグ九州2部' }
            ]}
        ];
    }

    // --- 階層アコーディオン 1項目 (地域) の描画 ------------------
    // option (A): 同じ name="regionName" を共有するので
    //             他地域の <details> を開くと自動で閉じる
    renderAccordionItem(item, groups, defaultOpen, type, regionName) {
        const isOpen = defaultOpen.region === item.key;
        const openAttr = isOpen ? 'open' : '';

        // サブ (1部/2部) がある場合はネストアコーディオン
        if (Array.isArray(item.divisions) && item.divisions.length > 0) {
            // 地域内の division も排他: 地域ごとに独自の name を発行する
            const divisionName = `${type}-${item.key}-division`;
            const subHtml = item.divisions.map(div => {
                const subOpen  = isOpen && defaultOpen.division === div.key;
                const subOpenAttr = subOpen ? 'open' : '';
                const teams = groups[div.leagueName] || [];
                return `
                    <details class="league-accordion league-accordion--division" name="${divisionName}" ${subOpenAttr}>
                        <summary class="league-accordion__summary league-accordion__summary--division">
                            <span class="league-accordion__chevron"><i class="fas fa-chevron-right"></i></span>
                            <span class="league-accordion__label">${this.escapeHtml(div.label)}</span>
                            <span class="league-accordion__count">${teams.length}チーム</span>
                        </summary>
                        <div class="league-accordion__body">
                            ${this.renderLeagueTable(div.leagueName, teams)}
                        </div>
                    </details>
                `;
            }).join('');
            return `
                <details class="league-accordion league-accordion--region" name="${regionName}" ${openAttr}>
                    <summary class="league-accordion__summary league-accordion__summary--region">
                        <span class="league-accordion__chevron"><i class="fas fa-chevron-right"></i></span>
                        <span class="league-accordion__label">${this.escapeHtml(item.label)}</span>
                    </summary>
                    <div class="league-accordion__body league-accordion__body--nested">
                        ${subHtml}
                    </div>
                </details>
            `;
        }

        // リーフ地域 (ネストなし)
        const teams = groups[item.leagueName] || [];
        return `
            <details class="league-accordion league-accordion--region" name="${regionName}" ${openAttr}>
                <summary class="league-accordion__summary league-accordion__summary--region">
                    <span class="league-accordion__chevron"><i class="fas fa-chevron-right"></i></span>
                    <span class="league-accordion__label">${this.escapeHtml(item.label)}</span>
                    <span class="league-accordion__count">${teams.length}チーム</span>
                </summary>
                <div class="league-accordion__body">
                    ${this.renderLeagueTable(item.leagueName, teams)}
                </div>
            </details>
        `;
    }

    // --- リーフ順位表 --------------------------------------------
    renderLeagueTable(leagueName, teams) {
        if (!teams || teams.length === 0) {
            return `
                <div style="padding:16px; color:#888; background:#fafbfe; border:1px dashed #d3dae3; border-radius:6px; margin:8px 0;">
                    <i class="fas fa-info-circle"></i> ${this.escapeHtml(leagueName)} のデータがまだありません
                </div>
            `;
        }
        const prefectureHeader = teams.some(t => t.prefectureName) ? '<th>所属</th>' : '';
        return `
            <div class="league-group-block">
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>順位</th>
                            <th>チーム名</th>
                            ${prefectureHeader}
                            <th>勝点</th>
                            <th>試合</th>
                            <th>勝</th>
                            <th>分</th>
                            <th>負</th>
                            <th>得点</th>
                            <th>失点</th>
                            <th>得失差</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${teams.map(t => this.createLeagueTeamRow(t, !!prefectureHeader)).join('')}
                    </tbody>
                </table>
            </div>
        `;
    }

    createLeagueTeamRow(team, showPrefecture) {
        const goalsFor = team.goalsFor ?? 0;
        const goalsAgainst = team.goalsAgainst ?? 0;
        const goalDiff = goalsFor - goalsAgainst;
        // P1-3: 表示順位は leagueRank 優先
        const rankVal = (team.leagueRank != null ? team.leagueRank : team.rank);
        const rank = rankVal || '-';
        const rankClass = (typeof rank === 'number' && rank <= 3) ? `rank-${rank}` : 'rank-other';

        // ★ Phase 9-1h: チーム名内の "U-18" などが途中で割れないよう <wbr> を挿入
        const teamNameDisplay = this.escapeHtml(team.name).replace(/(U-?\d+)/g, '<wbr>$1');

        return `
            <tr>
                <td><span class="rank-badge ${rankClass}">${rank}</span></td>
                <td><strong>${teamNameDisplay}</strong>${this.getTournamentBadge(team.name)}</td>
                ${showPrefecture ? `<td>${this.escapeHtml(team.prefectureName || '-')}</td>` : ''}
                <td><strong>${team.points ?? 0}</strong></td>
                <td>${team.played ?? 0}</td>
                <td>${team.won ?? 0}</td>
                <td>${team.drawn ?? 0}</td>
                <td>${team.lost ?? 0}</td>
                <td>${goalsFor}</td>
                <td>${goalsAgainst}</td>
                <td style="color: ${goalDiff > 0 ? '#28a745' : goalDiff < 0 ? '#dc3545' : '#666'}">
                    ${goalDiff > 0 ? '+' : ''}${goalDiff}
                </td>
            </tr>
        `;
    }

    escapeHtml(str) {
        if (str == null) return '';
        return String(str).replace(/[&<>"']/g, c => ({
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#39;'
        }[c]));
    }
}

// アプリケーションの初期化
let app;
window.addEventListener('DOMContentLoaded', () => {
    app = new SoccerApp();
});
