# Kararsızım

Kararsız kalanların topluluğa soru sorup anket açtığı bir web uygulaması.
Ayrıntılı ürün ve teknik kılavuz: [docs/kararsızım-proje-planı.md](docs/kararsızım-proje-planı.md).

**Teknoloji:** Python 3.12, Django 5.2 LTS, Supabase Postgres (yerelde SQLite), Vercel.

## Yerel kurulum

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate   |   macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # DEBUG=True yap; SECRET_KEY'i doldur
python manage.py migrate
python manage.py createsuperuser   # e-posta, kullanıcı adı, parola
python manage.py runserver
```

Uygulama: http://127.0.0.1:8000 · Yönetim: http://127.0.0.1:8000/admin/

`DATABASE_URL` boşsa yerel `db.sqlite3` kullanılır.

## Testler

```bash
python manage.py test
```

## Ortam değişkenleri

| Ad | Açıklama |
|---|---|
| `SECRET_KEY` | Django gizli anahtarı. `DEBUG=False` iken zorunlu. |
| `DEBUG` | Yerelde `True`, üretimde `False`. |
| `DATABASE_URL` | Postgres bağlantı dizesi. Boşsa SQLite. |

## Yayın (Vercel + Supabase)

```
tarayıcı ──► Vercel (Django, bölge fra1) ──► Supabase Postgres (eu-central-1, Frankfurt)
              statik dosyalar CDN'den        Transaction pooler, port 6543
```

Yapılandırma dosyaları depoda hazır: `vercel.json` (fonksiyonu veritabanıyla aynı bölgeye, `fra1`, sabitler),
`.python-version` (Python 3.12), `requirements.txt`. Vercel, Django'yu depo kökündeki `manage.py` ve
`WSGI_APPLICATION` üzerinden tanır; `STATIC_ROOT` tanımlı olduğu için `collectstatic`'i build sırasında
kendisi çalıştırır. Ek bir build ayarı gerekmez.

### Vercel ortam değişkenleri

Vercel → Project → Settings → Environment Variables. **Production, Preview ve Development** kutularını işaretle.

| Ad | Değer |
|---|---|
| `SECRET_KEY` | Uzun rastgele bir dizi (aşağıdaki komutla üret). **Sensitive** olarak işaretle. |
| `DATABASE_URL` | Supabase **Transaction pooler** dizesi (port **6543**). **Sensitive** olarak işaretle. |
| `DEBUG` | Tanımlama ya da `False` yaz. Tanımlı değilse zaten `False`'tur. |

Gizli anahtarı yerelde üretip yalnızca Vercel paneline yapıştır; bir dosyaya yazma, depoya koyma:

```bash
python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
```

Transaction pooler dizesi: Supabase → proje → **Connect** → bağlantı türü **Transaction pooler** → URI.
Kalıbı şöyle olmalı (parolanı sen yaz):

```
postgresql://postgres.<proje-ref>:<PAROLA>@aws-1-eu-central-1.pooler.supabase.com:6543/postgres
```

Yerel `.env`'deki **Session pooler** dizesiyle (port 5432) aynı yer ve kullanıcı; yalnızca port farklıdır.

### İlk yayın adımları

1. Kod GitHub'da `main` dalında olmalı (`git push origin main`).
2. Veritabanı şeması Supabase'e **yerelden** uygulanır, Vercel build'inde çalışmaz: `.env`'de Session pooler
   adresiyle `python manage.py migrate`. Yeni tablo oluşturan her migration'dan sonra o tabloda RLS'i de aç
   (bkz. `CLAUDE.md`).
3. Vercel'de **Add New → Project**, GitHub deposunu (`unalnamdar/Kararsizim`) içe aktar. Framework otomatik
   **Django** olarak algılanır; Build/Output ayarlarına dokunma.
4. Deploy'dan **önce** yukarıdaki üç ortam değişkenini ekle.
5. **Deploy**'a bas ve build'in bitmesini bekle.
6. Yönetici hesabı: yerelde, `.env` Supabase'e bağlıyken `python manage.py createsuperuser`
   (e-posta, kullanıcı adı, parola). Hesap Supabase'te oluşur ve yayındaki `/admin/` ile de çalışır.

Canlı adres: https://kararsizim-orcin.vercel.app

> Not: Vercel proje adı başkası tarafından alınmışsa adrese bir ek getirir. `kararsizim.vercel.app` başka birine ait; paylaşacağın adres, Vercel'in projenin **Domains** sayfasında gösterdiğidir.

### Yayın sonrası kontrol listesi

- Ana sayfa açılıyor, stiller ve yazı tipi yüklü (statik dosyalar CDN'den).
- Kayıt ol → anket oluştur → başka bir tarayıcıdan (ya da gizli pencereden) misafir olarak oy ver.
- `/admin/` giriş sayfası açılıyor ve yönetici hesabıyla girilebiliyor.
- Adres `https://` ile açılıyor; `http://` yönlendiriliyor.
- Supabase tabloları herkese açık anahtarla okunamıyor (Supabase panelinde Security Advisor'da hata yok).

### Notlar ve sorun giderme

- **Hangi adres:** Vercel her deploy için ayrı bir adres de üretir (`...-abc123-....vercel.app`). Bu adresler projenin
  **Deployment Protection** ayarına (Settings → Deployment Protection) bağlı olarak Vercel girişi isteyebilir.
  Paylaşacağın adres projenin üretim adresidir (`<proje>.vercel.app`); orası anonim ziyaretçilere açık olmalı.
  Açılmıyorsa ya da giriş soruyorsa önce bu ayara bak.
- **Loglar:** Vercel → Project → Logs. Başarısız isteklerin hata ayrıntısı oraya düşer (`LOGGING` ayarı bunun içindir).
- **`ImproperlyConfigured: SECRET_KEY ...`:** `SECRET_KEY` ortam değişkeni eksik ya da yanlış ortama eklenmiş.
- **`DisallowedHost`:** Adres `*.vercel.app` dışında bir alan adıysa `config/settings.py` içindeki `ALLOWED_HOSTS` ve
  `CSRF_TRUSTED_ORIGINS` listelerine eklenmeli (özel alan adı Faz 6).
- **Bağlantı hataları (`OperationalError`):** `DATABASE_URL`'nin parolasını ve portunu (**6543**) kontrol et; parolada
  özel karakter varsa URL-kodlu yaz.
- **Yeni ortam değişkeni ya da değişiklik** yalnızca yeni bir deploy'dan sonra geçerli olur (Vercel → Deployments → Redeploy).
- **Yerel üretim denemesi:** `DEBUG=False SECRET_KEY=<uzun-rastgele> DATABASE_URL= python manage.py runserver --insecure`
  statik dosyalarıyla birlikte çalışır; HTTPS yönlendirmesi nedeniyle tarayıcıdan değil, `X-Forwarded-Proto: https`
  başlığıyla `curl` ile denenir.
