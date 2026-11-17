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

Yayın adımları Faz 5'te eklenecek.
