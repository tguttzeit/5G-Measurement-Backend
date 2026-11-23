"""Integration tests for the per-user favorite config fields."""
from sqlalchemy import select

from app.config_override_spec import CONFIG_OVERRIDE_SPEC, specs_in_display_order
from app.models.favorite_config_field import UserFavoriteConfigField
from app.models.user import User
from tests.integration.test_api.test_commands import (
    _create_superuser,
    _login,
    _superuser_headers,
    password_helper,
)

URL = "/favorite-config-fields"
FIRST, SECOND = (spec.key for spec in specs_in_display_order()[:2])
LAST = specs_in_display_order()[-1].key


def _second_superuser_headers(db_session, test_client):
    _create_superuser(db_session, "second-admin")
    return {"Authorization": f"Bearer {_login(test_client, 'second-admin')}"}


def _stored(db_session):
    db_session.expire_all()
    return sorted(
        (row.user_id, row.field_key)
        for row in db_session.scalars(select(UserFavoriteConfigField))
    )


def test_get_requires_auth(test_client):
    assert test_client.get(URL).status_code == 401


def test_put_requires_auth_and_stores_nothing(test_client, db_session):
    assert test_client.put(URL, json={"field_keys": [FIRST]}).status_code == 401
    assert _stored(db_session) == []


def test_regular_user_gets_403_and_stores_nothing(test_client, db_session):
    db_session.add(
        User(
            email="regular-user",
            hashed_password=password_helper.hash("correct-horse-battery-staple"),
            is_active=True,
            is_superuser=False,
            is_verified=False,
        )
    )
    db_session.commit()
    headers = {"Authorization": f"Bearer {_login(test_client, 'regular-user')}"}

    assert test_client.get(URL, headers=headers).status_code == 403
    assert test_client.put(URL, json={"field_keys": [FIRST]}, headers=headers).status_code == 403
    assert _stored(db_session) == []


def test_get_defaults_to_no_favorites(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)

    assert test_client.get(URL, headers=headers).json() == {"field_keys": []}


def test_put_stores_the_keys_and_returns_them_in_display_order(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)

    response = test_client.put(URL, json={"field_keys": [LAST, FIRST]}, headers=headers)

    assert response.status_code == 200
    assert response.json() == {"field_keys": [FIRST, LAST]}
    assert test_client.get(URL, headers=headers).json() == {"field_keys": [FIRST, LAST]}


def test_put_replaces_the_previous_favorites(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)
    test_client.put(URL, json={"field_keys": [FIRST, SECOND]}, headers=headers)

    test_client.put(URL, json={"field_keys": [SECOND, LAST]}, headers=headers)

    assert test_client.get(URL, headers=headers).json() == {"field_keys": [SECOND, LAST]}
    assert len(_stored(db_session)) == 2


def test_put_empty_list_clears_the_favorites(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)
    test_client.put(URL, json={"field_keys": [FIRST]}, headers=headers)

    response = test_client.put(URL, json={"field_keys": []}, headers=headers)

    assert response.json() == {"field_keys": []}
    assert _stored(db_session) == []


def test_every_registry_field_can_be_a_favorite(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)
    keys = [spec.key for spec in CONFIG_OVERRIDE_SPEC]

    response = test_client.put(URL, json={"field_keys": keys}, headers=headers)

    assert response.status_code == 200
    assert sorted(response.json()["field_keys"]) == sorted(keys)


def test_unknown_key_gives_422_naming_only_it_and_keeps_the_stored_favorites(
    test_client, db_session
):
    headers = _superuser_headers(db_session, test_client)
    test_client.put(URL, json={"field_keys": [FIRST]}, headers=headers)

    response = test_client.put(
        URL, json={"field_keys": [SECOND, "no_such_field"]}, headers=headers
    )

    assert response.status_code == 422
    assert "no_such_field" in response.text
    assert SECOND not in response.text
    assert test_client.get(URL, headers=headers).json() == {"field_keys": [FIRST]}


def test_duplicate_keys_give_422_and_store_nothing(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)

    response = test_client.put(URL, json={"field_keys": [FIRST, FIRST]}, headers=headers)

    assert response.status_code == 422
    assert _stored(db_session) == []


def test_more_keys_than_the_registry_has_gives_422(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)

    response = test_client.put(
        URL, json={"field_keys": [FIRST] * (len(CONFIG_OVERRIDE_SPEC) + 1)}, headers=headers
    )

    assert response.status_code == 422
    assert _stored(db_session) == []


def test_a_user_id_in_the_body_is_rejected(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)

    response = test_client.put(URL, json={"field_keys": [], "user_id": 99}, headers=headers)

    assert response.status_code == 422


def test_favorites_of_a_removed_field_are_ignored_on_read(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)
    user = db_session.scalars(select(User)).one()
    db_session.add_all(
        [
            UserFavoriteConfigField(user_id=user.id, field_key=FIRST),
            UserFavoriteConfigField(user_id=user.id, field_key="long_gone_field"),
        ]
    )
    db_session.commit()

    assert test_client.get(URL, headers=headers).json() == {"field_keys": [FIRST]}


def test_put_drops_stored_favorites_of_a_removed_field(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)
    user = db_session.scalars(select(User)).one()
    db_session.add(UserFavoriteConfigField(user_id=user.id, field_key="long_gone_field"))
    db_session.commit()

    test_client.put(URL, json={"field_keys": [FIRST]}, headers=headers)

    assert _stored(db_session) == [(user.id, FIRST)]


def test_users_do_not_see_or_change_each_others_favorites(test_client, db_session):
    first_headers = _superuser_headers(db_session, test_client)
    second_headers = _second_superuser_headers(db_session, test_client)
    test_client.put(URL, json={"field_keys": [FIRST]}, headers=first_headers)

    assert test_client.get(URL, headers=second_headers).json() == {"field_keys": []}
    test_client.put(URL, json={"field_keys": [LAST]}, headers=second_headers)

    assert test_client.get(URL, headers=first_headers).json() == {"field_keys": [FIRST]}
    assert test_client.get(URL, headers=second_headers).json() == {"field_keys": [LAST]}


def test_deleting_a_user_removes_their_favorites(test_client, db_session):
    headers = _superuser_headers(db_session, test_client)
    test_client.put(URL, json={"field_keys": [FIRST]}, headers=headers)

    db_session.delete(db_session.scalars(select(User)).one())
    db_session.commit()

    assert _stored(db_session) == []
