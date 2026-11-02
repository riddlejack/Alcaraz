"""The all-tier model and the current Alcaraz.

* :mod:`~tennislab.alltier.source` reads the archive's tour, qualifying/Challenger and
  Futures files and dates every row;
* :mod:`~tennislab.alltier.table` replays them into the point-in-time all-tier table;
* :mod:`~tennislab.alltier.kalman` is the table's serve/return filter and its tuning;
* :mod:`~tennislab.alltier.pointmodel` turns serve-point probabilities into match odds;
* :mod:`~tennislab.alltier.model` fits the all-tier model on the table;
* :mod:`~tennislab.alltier.pool` pools it with the previous version into the current
  Alcaraz;
* :mod:`~tennislab.alltier.cli` is ``tennislab current``.
"""
