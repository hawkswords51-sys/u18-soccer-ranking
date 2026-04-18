// 実在チーム名生成器
// 各都道府県の実在する高校・ユースチームの一般的なパターンを使用

class RealTeamsGenerator {
    constructor() {
        // 都道府県別の実在チーム名パターン
        this.realTeamPatterns = {
            common: [
                '{pref}高校',
                '{pref}FC U-18',
                '{pref}ユース',
                '{pref}東高校',
                '{pref}西高校',
                '{pref}南高校',
                '{pref}北高校',
                '{pref}中央高校',
                '{pref}第一高校',
                '{pref}商業高校'
            ]
        };

        // 実在の有名高校の接尾辞
        this.schoolSuffixes = [
            '学園',
            '学院',
            '実業',
            '工業',
            '商業',
            '東',
            '西',
            '南',
            '北',
            '中央'
        ];
    }

    generateRealTeamsForPrefecture(prefId, prefName, existingTeams) {
        // 秋田県は9チーム構成（例外）
        const targetCount = prefId === 'akita' ? 9 : 10;
        const currentCount = existingTeams.length;

        if (currentCount >= targetCount) {
            return existingTeams;
        }

        const additionalCount = targetCount - currentCount;
        const newTeams = [];

        // 都道府県名から「県」「都」「府」「道」を除去
        const baseName = prefName.replace(/[県都府道]/g, '');

        for (let i = 0; i < additionalCount; i++) {
            const rank = currentCount + i + 1;
            const teamName = this.generateRealisticTeamName(baseName, i, existingTeams);
            const league = this.determineLeague(prefName, rank);
            const stats = this.generateRealisticStats(rank);

            newTeams.push({
                id: `${prefId}_${rank}_${Date.now()}`,
                name: teamName,
                league: league,
                rank: stats.leagueRank,
                points: stats.points,
                played: stats.played,
                won: stats.won,
                drawn: stats.drawn,
                lost: stats.lost,
                goalsFor: stats.goalsFor,
                goalsAgainst: stats.goalsAgainst,
                prefectureRank: rank
            });
        }

        return [...existingTeams, ...newTeams];
    }

    generateRealisticTeamName(baseName, index, existingTeams) {
        const existingNames = existingTeams.map(t => t.name);

        const patterns = [
            `${baseName}東高校`,
            `${baseName}西高校`,
            `${baseName}南高校`,
            `${baseName}北高校`,
            `${baseName}中央高校`,
            `${baseName}商業高校`,
            `${baseName}工業高校`,
            `${baseName}実業高校`,
            `${baseName}第一高校`,
            `${baseName}第二高校`,
            `${baseName}学院高校`,
            `${baseName}学園高校`,
            `${baseName}国際高校`,
            `${baseName}FC U-18`
        ];

        // 既存の名前と重複しないものを選択
        for (const pattern of patterns) {
            if (!existingNames.includes(pattern)) {
                return pattern;
            }
        }

        // すべて使用済みの場合はインデックス付き
        return `${baseName}${index + 4}高校`;
    }

    determineLeague(prefName, rank) {
        // 都道府県名から「県」「都」「府」「道」を除去してリーグ名を生成
        const baseName = prefName.replace(/[県都府道]/g, '');

        if (rank <= 3) {
            return `${baseName}1部リーグ`;
        } else if (rank <= 6) {
            return `${baseName}2部リーグ`;
        } else {
            return `${baseName}3部リーグ`;
        }
    }

    generateRealisticStats(rank) {
        const played = 14 + Math.floor(Math.random() * 3);

        let winRate, drawRate;
        if (rank <= 3) {
            winRate = 0.65 + Math.random() * 0.15;
            drawRate = 0.15;
        } else if (rank <= 6) {
            winRate = 0.45 + Math.random() * 0.15;
            drawRate = 0.20;
        } else {
            winRate = 0.25 + Math.random() * 0.15;
            drawRate = 0.15;
        }

        const won = Math.floor(played * winRate);
        const drawn = Math.floor((played - won) * drawRate / (1 - winRate));
        const lost = played - won - drawn;
        const points = won * 3 + drawn;

        const goalsPerGame = rank <= 3 ? 2.2 : rank <= 6 ? 1.6 : 1.2;
        const concededPerGame = rank <= 3 ? 1.3 : rank <= 6 ? 1.9 : 2.4;

        const goalsFor = Math.floor(played * goalsPerGame);
        const goalsAgainst = Math.floor(played * concededPerGame);

        return {
            leagueRank: Math.min(rank, 10),
            points,
            played,
            won,
            drawn,
            lost,
            goalsFor,
            goalsAgainst
        };
    }
}

window.realTeamsGenerator = new RealTeamsGenerator();
