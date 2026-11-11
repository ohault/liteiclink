# Initial 64b/66b receive block synchronization

`BlockSynchronizer` accepts 66-bit candidate blocks from a continuous-bit
gearbox. `BlockRX` defaults to one-bit input words and can instead accept
parameterized raw PMA word widths directly. A header is valid when its two bits differ (`10` for data or `01`
for control). Candidate block bits are ordered least-significant bit first,
so the header occupies bits 1:0 of the packed block.

While unlocked, candidate blocks are consumed and discarded. The synchronizer
acquires lock after a 64-header window with no invalid headers. While locked,
blocks are passed through; 16 invalid headers in a 64-header window clear
lock and request a slip. While unlocked, each invalid header requests a slip
(IEEE 802.3 Clause 49 Figure 49-14), so a wrong alignment is left after one or
two candidates on scrambled data. A slip
request asks the upstream `BitstreamGearbox` to discard its earliest buffered
bit and present candidates at the next possible bit boundary. The synchronizer
then repeats the header checks until it reacquires lock.

`BitstreamGearbox.slip` is a one-cycle request. It suppresses the current
output transfer and removes one buffered bit; if the buffer is empty, it
remembers the request until a bit arrives. This keeps the slip operation
separate from transceiver-specific word alignment.

The thresholds follow IEEE 802.3 Clause 49 Figure 49-14. The test covers
one-bit initial misalignment through the gearbox, lock acquisition, lock
loss, and reacquisition. The output blocks remain scrambled; descrambling and
control-block interpretation are separate PCS stages.

See [IEEE 802.3 Clause 49.2.9 and Figure 49-14](https://www.my-wire.de/schnittstellenbeschreibung/ethernet.pdf).
