// 簡易版：クリック可能な都道府県リスト
const prefecturesDataSimple = {
    hokkaido: { name: '北海道', region: '北海道' },
    aomori: { name: '青森県', region: '東北' },
    iwate: { name: '岩手県', region: '東北' },
    miyagi: { name: '宮城県', region: '東北' },
    akita: { name: '秋田県', region: '東北' },
    yamagata: { name: '山形県', region: '東北' },
    fukushima: { name: '福島県', region: '東北' },
    ibaraki: { name: '茨城県', region: '関東' },
    tochigi: { name: '栃木県', region: '関東' },
    gunma: { name: '群馬県', region: '関東' },
    saitama: { name: '埼玉県', region: '関東' },
    chiba: { name: '千葉県', region: '関東' },
    tokyo: { name: '東京都', region: '関東' },
    kanagawa: { name: '神奈川県', region: '関東' },
    niigata: { name: '新潟県', region: '北信越' },
    toyama: { name: '富山県', region: '北信越' },
    ishikawa: { name: '石川県', region: '北信越' },
    fukui: { name: '福井県', region: '北信越' },
    yamanashi: { name: '山梨県', region: '関東' },
    nagano: { name: '長野県', region: '北信越' },
    gifu: { name: '岐阜県', region: '東海' },
    shizuoka: { name: '静岡県', region: '東海' },
    aichi: { name: '愛知県', region: '東海' },
    mie: { name: '三重県', region: '東海' },
    shiga: { name: '滋賀県', region: '関西' },
    kyoto: { name: '京都府', region: '関西' },
    osaka: { name: '大阪府', region: '関西' },
    hyogo: { name: '兵庫県', region: '関西' },
    nara: { name: '奈良県', region: '関西' },
    wakayama: { name: '和歌山県', region: '関西' },
    tottori: { name: '鳥取県', region: '中国' },
    shimane: { name: '島根県', region: '中国' },
    okayama: { name: '岡山県', region: '中国' },
    hiroshima: { name: '広島県', region: '中国' },
    yamaguchi: { name: '山口県', region: '中国' },
    tokushima: { name: '徳島県', region: '四国' },
    kagawa: { name: '香川県', region: '四国' },
    ehime: { name: '愛媛県', region: '四国' },
    kochi: { name: '高知県', region: '四国' },
    fukuoka: { name: '福岡県', region: '九州' },
    saga: { name: '佐賀県', region: '九州' },
    nagasaki: { name: '長崎県', region: '九州' },
    kumamoto: { name: '熊本県', region: '九州' },
    oita: { name: '大分県', region: '九州' },
    miyazaki: { name: '宮崎県', region: '九州' },
    kagoshima: { name: '鹿児島県', region: '九州' },
    okinawa: { name: '沖縄県', region: '九州' }
};

// 地域別にグループ化
const regions = {
    '北海道': ['hokkaido'],
    '東北': ['aomori', 'iwate', 'miyagi', 'akita', 'yamagata', 'fukushima'],
    '関東': ['ibaraki', 'tochigi', 'gunma', 'saitama', 'chiba', 'tokyo', 'kanagawa', 'yamanashi'],
    '北信越': ['niigata', 'toyama', 'ishikawa', 'fukui', 'nagano'],
    '東海': ['gifu', 'shizuoka', 'aichi', 'mie'],
    '関西': ['shiga', 'kyoto', 'osaka', 'hyogo', 'nara', 'wakayama'],
    '中国': ['tottori', 'shimane', 'okayama', 'hiroshima', 'yamaguchi'],
    '四国': ['tokushima', 'kagawa', 'ehime', 'kochi'],
    '九州': ['fukuoka', 'saga', 'nagasaki', 'kumamoto', 'oita', 'miyazaki', 'kagoshima', 'okinawa']
};

// 地域別リスト生成クラス
class RegionListGenerator {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
    }

    async generate() {
        // データマネージャーの初期化を待つ
        await new Promise(resolve => {
            const checkData = setInterval(() => {
                if (dataManager.data) {
                    clearInterval(checkData);
                    resolve();
                }
            }, 100);
        });

        console.log('Region list generation started');
        this.drawRegions();
        console.log('Region list generation completed');
    }

    drawRegions() {
        const html = Object.entries(regions).map(([regionName, prefIds]) => {
            const prefButtons = prefIds.map(prefId => {
                const prefData = prefecturesDataSimple[prefId];
                const leagueLevel = dataManager.getHighestLeagueLevel(prefId);
                const levelClass = `level-${leagueLevel}`;
                
                return `
                    <button class="pref-button ${levelClass}" data-pref-id="${prefId}" data-pref-name="${prefData.name}">
                        ${prefData.name}
                    </button>
                `;
            }).join('');

            return `
                <div class="region-group">
                    <h3 class="region-title">${regionName}</h3>
                    <div class="pref-grid">
                        ${prefButtons}
                    </div>
                </div>
            `;
        }).join('');

        this.container.innerHTML = html;

        // クリックイベントを設定
        this.container.querySelectorAll('.pref-button').forEach(button => {
            button.addEventListener('click', () => {
                const prefId = button.dataset.prefId;
                const prefName = button.dataset.prefName;
                console.log(`Button clicked: ${prefId} (${prefName})`);
                this.onPrefectureClick(prefId, prefName);
            });
        });
    }

    onPrefectureClick(prefId, prefName) {
        // モーダル表示イベントを発火
        const event = new CustomEvent('prefectureSelected', {
            detail: { prefId, prefName }
        });
        document.dispatchEvent(event);
    }
}
