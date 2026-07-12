# 0002 is a no-op on the database side: 0001_initial now declares both
# models with the final field set, but the on-disk sqlite already has
# the corresponding tables. The first time the project is set up
# against an existing database, run:
#
#     python manage.py migrate main_app --fake-initial
#
# to record 0001 as applied without re-running CREATE TABLE.  On a
# fresh database 0001 will create both tables with the right columns
# and 0002 has nothing left to do.
#
# We keep this empty migration around so that subsequent revisions
# (e.g. adding new fields later) have a stable anchor point.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('main_app', '0001_initial'),
    ]

    operations: list = []
