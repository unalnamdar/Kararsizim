# CLAUDE.md

## Önce oku

Projenin tek doğruluk kaynağı: [docs/kararsızım-proje-planı.md](docs/kararsızım-proje-planı.md). Her oturumda önce onu oku; ürün kuralları, veri modeli, uçlar, arayüz yönü ve fazlar oradadır. Bu dosya yalnızca çalışma kurallarını özetler — kılavuzla çelişirse kılavuz geçerlidir.

## Çalışma şekli

- İş fazlara bölünmüştür. Yalnızca kullanıcının söylediği fazı uygula; fazın kabul kriterleri sağlanınca dur, özet ver. Sonraki faza kendiliğinden geçme.
- Bir karar kılavuzda yoksa ya da kılavuzla çelişiyorsa kod yazmadan önce sor. Netleşen kararları kılavuzdaki "Netleştirilen kararlar" bölümüne işle.
- Prototip: yeni bağımlılık eklemeden önce sor. DRF, Celery, Redis, React, Tailwind, Docker, npm ekleme.
- Her fazda ilgili kısım için Django testleri yaz.

## Kod kuralları

- Kod, değişken, model adları ve commit mesajları **İngilizce**; kullanıcıya görünen tüm metinler **Türkçe**. URL yolları Türkçe.
- E-posta hiçbir sayfada, HTML'de veya JSON'da görünmez; herkese açık kimlik yalnızca kullanıcı adıdır.
- Gizli değerler yalnızca ortam değişkenlerinde (`SECRET_KEY`, `DATABASE_URL`, `DEBUG`). `.env` git'e girmez; gizli anahtarları kendin üretip dosyaya yazma.
- Renk, boşluk ve yarıçaplar yalnızca `static/css/tokens.css` içindeki CSS değişkenlerinden gelir.

## Komutlar (Windows, proje kökünden)

```bash
.venv/Scripts/python.exe manage.py runserver
.venv/Scripts/python.exe manage.py test
.venv/Scripts/python.exe manage.py makemigrations
.venv/Scripts/python.exe manage.py migrate
DEBUG=False SECRET_KEY=<uzun-rastgele> .venv/Scripts/python.exe manage.py check --deploy
```

- `DATABASE_URL` boşsa yerel `db.sqlite3` kullanılır. Supabase migration'ları yerelden, Session pooler (5432) ile uygulanır; Vercel build'inde migration çalıştırılmaz.
- Supabase projesi: `kararsizim` (ref `wtkfxgntvoznkczsckke`, eu-central-1). Session pooler host'u `aws-1-eu-central-1.pooler.supabase.com` (aws-0 değil). Yerel `.env` bu projeye bağlı.
- Yayın: Vercel (bölge `fra1`, `vercel.json`) + Supabase. Vercel ortam değişkenleri `SECRET_KEY` ve `DATABASE_URL` (**Transaction pooler, port 6543**); adımlar README'de ("Yayın"). Gizli değerleri ben üretmem/yazmam; kullanıcı Vercel paneline kendisi girer.
- `public` şemasındaki tüm tablolarda RLS açık (politikasız) ve `anon`/`authenticated` yetkileri geri alındı; Django tablo sahibi olduğu için etkilenmez. **Yeni tablo oluşturan her migration'dan sonra** o tabloda da RLS aç (`alter table public.<tablo> enable row level security;`) ve Supabase güvenlik uyarılarını kontrol et.
- Testleri Supabase'e karşı çalıştırırken `--keepdb` kullan (pooler açık bağlantı tuttuğu için `test_postgres` silinemiyor; ~3 dk sürer). Günlük geliştirmede SQLite ile test etmek daha hızlıdır: `.env`'e dokunmadan komutun önüne boş değişken koy, ör. `DATABASE_URL= .venv/Scripts/python.exe manage.py test` (ortamdaki boş değer `.env`'i ezer).

## Git

- Ana dal `main`, remote `origin` → https://github.com/unalnamdar/Kararsizim. Her faz kabul kriterleri sağlanınca o faz için commit at ve `git push origin main` ile pushla.
- Dosyaları tek tek ekle (`git add -A` kullanma); `.env` ve `.idea/` commit'lenmez.
