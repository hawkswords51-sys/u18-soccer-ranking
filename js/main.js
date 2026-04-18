// メインアプリケーション
class SoccerApp {
    constructor() {
        this.map = null;
        this.currentPrefecture = null;
        this.init();
    }

    async init() {
        console.log('SoccerApp initialization started');
        
        // 地域別リストの初期化
        this.map = new RegionListGenerator('japanMap');
        await this.map.generate();
        console.log('Region list generated');

        // イベントリスナーの設定
        this.setupEventListeners();
        console.log('Event listeners setup completed');

        // 検索機能の初期化
        this.setupSearch();
        console.log('Search functionality initialized');
    }

    setupEventListeners() {
        // 都道府県選択イベント
        document.addEventListener('prefectureSelected', (e) => {
            console.log('prefectureSelected event received in main.js:', e.detail);
            this.showPrefectureDetail(e.detail.prefId, e.detail.prefName);
        });

        // モーダル閉じるボタン
        document.getElementById('closeModal').addEventListener('click', () => {
            this.closeModal();
        });

        // モーダル外クリック
        document.getElementById('detailModal').addEventListener('click', (e) => {
            if (e.target.id === 'detailModal') {
                this.closeModal();
            }
        });

        // タブ切り替え
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                this.switchTab(e.target.dataset.tab);
            });
        });

        // ホームボタン
        document.getElementById('homeBtn').addEventListener('click', (e) => {
            e.preventDefault();
            this.showHome();
        });

        // 検索ボタン
        document.getElementById('searchBtn').addEventListener('click', (e) => {
            e.preventDefault();
            this.toggleSearch();
        });

        // ESCキーでモーダルを閉じる
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                this.closeModal();
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

        const html = results.map(team => `
            <div class="search-result-item" data-pref-id="${team.prefectureId}">
                <div class="search-result-team">${team.name}</div>
                <div class="search-result-info">
                    <span><i class="fas fa-map-marker-alt"></i> ${team.prefectureName}</span>
                    <span><i class="fas fa-trophy"></i> ${team.league}</span>
                    <span><i class="fas fa-sort-numeric-down"></i> 順位: ${team.rank}位</span>
                </div>
            </div>
        `).join('');

        container.innerHTML = html;

        // 検索結果のクリックイベント
        container.querySelectorAll('.search-result-item').forEach(item => {
            item.addEventListener('click', () => {
                const prefId = item.dataset.prefId;
                const pref = dataManager.getPrefecture(prefId);
                if (pref) {
                    this.showPrefectureDetail(prefId, pref.name);
                    this.showHome(); // 検索画面を閉じる
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

        console.log('Prefecture ID:', prefId);
        console.log('Prefecture Data:', pref);

        if (!pref || !pref.teams || pref.teams.length === 0) {
            alert(`この都道府県（${prefName}）のデータはまだ登録されていません。\nID: ${prefId}`);
            return;
        }

        // モーダルタイトル
        document.getElementById('modalTitle').innerHTML = `
            <i class="fas fa-map-marker-alt"></i> ${prefName}
        `;

        // 統計情報
        document.getElementById('teamCount').textContent = pref.teams.length;
        document.getElementById('topLeague').textContent = this.getTopLeagueName(pref.teams);

        // リーグ戦テーブル
        this.displayTeamsTable(pref.teams);

        // 大会成績テーブル
        this.displayChampionshipsTable(pref.championships || []);

        // モーダルを表示
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
            return 1;  // 1部 or undivided (東北, 北海道, etc.)
        }
        return 3;  // 都道府県リーグ
    }

    displayTeamsTable(teams) {
        const container = document.getElementById('teamsTable');

        // リーグ階層（プレミア→プリンス→都道府県）でソートし、同一リーグ内はリーグ順位で並べる
        const sortedTeams = [...teams].sort((a, b) => {
            const tierDiff = this.leagueTierPriority(a.league) - this.leagueTierPriority(b.league);
            if (tierDiff !== 0) return tierDiff;
            return a.rank - b.rank;
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
        const goalDiffClass = goalDiff > 0 ? 'positive' : goalDiff < 0 ? 'negative' : 'neutral';

        const rankClass = prefRank <= 3 ? `rank-${prefRank}` : 'rank-other';

        let leagueBadgeClass = 'prefecture';
        if (team.league.includes('プレミアリーグ')) {
            leagueBadgeClass = 'premier';
        } else if (team.league.includes('プリンスリーグ')) {
            leagueBadgeClass = 'prince';
        }

        return `
            <tr>
                <td>
                    <span class="rank-badge ${rankClass}">${prefRank}</span>
                </td>
                <td><strong>${team.name}</strong></td>
                <td>
                    <span class="league-badge ${leagueBadgeClass}">${team.league}</span>
                </td>
                <td>${team.rank}位</td>
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

    displayChampionshipsTable(championships) {
        const container = document.getElementById('championshipsTable');

        if (championships.length === 0) {
            container.innerHTML = `
                <div style="text-align: center; padding: 40px; color: #666;">
                    <i class="fas fa-trophy" style="font-size: 3rem; opacity: 0.3; margin-bottom: 15px;"></i>
                    <p>大会成績データがありません</p>
                </div>
            `;
            return;
        }

        const html = `
            <table class="data-table">
                <thead>
                    <tr>
                        <th>年度</th>
                        <th>大会名</th>
                        <th>出場チーム</th>
                        <th>成績</th>
                    </tr>
                </thead>
                <tbody>
                    ${championships.map(c => `
                        <tr>
                            <td>${c.year}年</td>
                            <td>${c.tournament}</td>
                            <td><strong>${c.team}</strong></td>
                            <td>${c.result}</td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        `;

        container.innerHTML = html;
    }

    switchTab(tabName) {
        // タブボタンの切り替え
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.classList.remove('active');
        });
        document.querySelector(`[data-tab="${tabName}"]`).classList.add('active');

        // タブコンテンツの切り替え
        document.querySelectorAll('.tab-content').forEach(content => {
            content.classList.remove('active');
        });
        document.getElementById(`${tabName}Tab`).classList.add('active');
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
}

// アプリケーションの初期化
let app;
window.addEventListener('DOMContentLoaded', () => {
    app = new SoccerApp();
});
