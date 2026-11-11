# IEEE 802.3 64b/66b scrambler convention

The PCS scrambler implements the Clause 49 self-synchronizing polynomial
`1 + x^39 + x^58`. The 2-bit synchronization header is outside the
scrambler interface. Only the 64-bit payload is processed, with payload bit 0
first in time.

For serialized payload bit `n`, the transmitter computes

```
scrambled[n] = payload[n] XOR scrambled[n - 39] XOR scrambled[n - 58]
```

The receiver computes

```
payload[n] = scrambled[n] XOR scrambled[n - 39] XOR scrambled[n - 58]
```

The transmitter delay line stores generated scrambled bits. The receiver
delay line stores received scrambled bits. In both, state bit 0 represents
the most recent bit; taps 38 and 57 therefore represent delays 39 and 58.
The line advances only on an accepted ready/valid transfer and continues
across 64-bit payload boundaries. It does not reset at a 66-bit block or
packet boundary.

Clause 49 does not prescribe an initial state. The RTL uses zero by default;
both ends need 58 payload bits to self-synchronize after differing states.
The fixed test vector uses all ones as a deterministic test seed, not as a
protocol requirement. Each input word below is transmitted least-significant
bit first:

| Payload input | Scrambled output |
| --- | --- |
| `0123456789abcdef` | `6b3a4d6789abcdef` |
| `fedcba9876543210` | `d967221875542ee3` |
| `0000000000000000` | `254bdc64d2445c81` |
| `ffffffffffffffff` | `c304a29cc958dce4` |

The convention follows IEEE 802.3 Clause 49.2.6 and Figure 49-8, including
its note that the most recent input bit is the lowest-order term. See
[IEEE 802.3 Clause 49.2.6](https://www.my-wire.de/schnittstellenbeschreibung/ethernet.pdf)
and the [IEEE 802.3 64b/66b scrambler discussion](https://www.ieee802.org/3/10G_study/email/save/msg03532.html).
