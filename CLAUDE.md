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

## Git

- Ana dal `main`. Her faz kabul kriterleri sağlanınca o faz için commit at; push yapma.
- Dosyaları tek tek ekle (`git add -A` kullanma); `.env` ve `.idea/` commit'lenmez.
