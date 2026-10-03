# PV-DIAL_codebase

## Databases

- The CLI and the app use `pvdials_dev` (`DATABASE_URL` in `.env`).
- Tests use `pvdials_test` (forced by `tests/conftest.py`; a guard refuses `pvdials_dev`).
- On a new machine create the test database first:

```
createdb pvdials_test
DATABASE_URL=postgresql://localhost:5432/pvdials_test python -m pvdials db init
```
