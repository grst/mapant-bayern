This folder contains an experimental agent skill to optimize karttapullautin
params based on real orienteering maps from omaps.me that serve as training
data.

First impression:

- optimizing dotknoll and cliff params does not work at all, likely because the
  training data is too sparse
- optimizing vegetation works somewhat, but given the results in some forests I
  know IRL I'm not totally convinced either. But again, the training data was
  very sparse.
- The metrics seem to favor paramsets that omit details in vegetation. While
  this makes the result indeed look more like a real orienteering map, I think
  the details visible when using the default kp settings can still be useful
  sometimes even if they are not always correct.

Some limitations:

- there are a quite some batch effects in the laser scan data. Partly known
  (like different las versions), partly unknown or hard to address (e.g. a
  forest in winter looks quite different than a forest in summer).
- time differences are a real issue. In Bavaria the laser scan data has been
  generated over the course of 10 years. I have been using maps with a time
  difference of 2 years only, but in some forests a lot can happen in 2 years,
  and the date when the map was last updated is not easy to retreive from
  omaps.me, so it might be wrong.
- some maps on omaps.me are photographed (bad), some are scanned (less bad) and
  only very few are digital (good).

In the end, I didn't end up using the "optimal" params found by that skill, but
took some inspiration from it.
