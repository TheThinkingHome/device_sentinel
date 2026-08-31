# Device Sentinel 0.19.9

Version 0.19.9 checks storage at two boundaries and repairs what it finds at the moment it finds it. Every damaged-row fault of the last three releases was one reader guarded at a time; this closes the class and removes the guards.

## Breaking

**The Storage Repair Card No Longer Asks Anything:** The card that offered Restore, Trim and Ignore is gone. Nobody can look at a damaged row and judge it, and Ignore froze the backup at the pre-damage file while the live file went on gathering history. Damage is now repaired automatically and the card that follows is a notice naming what was repaired and where the originals are.

**The Clocks Backup Is Retired:** `device_sentinel.clocks.last-good` is deleted on the first start after upgrading. The clocks file is derived, a lost clock restarts honestly at the current moment, and a restore has always deleted that file rather than restored it, so a backup of it protected nothing.

## Added

**Storage Is Checked At Load:** After every migration and before the first reader, every device record and every table row is checked. From that line on, nothing in the running integration meets a row or a record the check would not accept.

**Storage Is Checked At Save:** Every row is checked as it is written, and the whole outgoing document is checked at each save, which is what catches a row edited in place after it was written.

**Damage Is Repaired Where It Is Found:** An unreadable file at load is replaced from the last-good copy. Damage at load with a usable last-good copy is replaced from it, and the load runs again on the copy. Damage with no usable copy is repaired in place: a damaged table row is dropped, a record that is not a record is dropped, and a damaged field is reset to its default with the rest of the record kept. Damage found at save is repaired at that moment by the same rules. A damaged clocks file is discarded and rebuilds itself.

**Every Repair Copies The Originals First:** Both storage files and the last-good copy are copied to `trim_backups` before anything is changed. A system event records the repair, and one notice card names what was repaired and where the copies are.

**A Withdrawal Event:** `device_sentinel_withdrawn` fires when a to-do line leaves because its device left the watched set. It carries the device, its kinds and the reason, so an automation that paired a fault with that line can close without ever hearing "recovered" for a device that was never away.

## Changed

**The Last-Good Copy Is Made By A Rename:** Before each clean save, the live storage file is renamed to `device_sentinel.storage.last-good` and the new file is written in its place. The copy is therefore always the most recent file that passed the check: one save interval old while everything is healthy, and frozen at the last clean save while it is not. A save that repaired something writes the live file and leaves the copy alone, so a repaired file becomes the copy only after a later save proves it clean.

**The Load-Time And Midnight Backups Are Gone:** The rotation above does their work. So do the midnight verification pass and the rule that withheld the copy after a repair.

**Reader Guards Removed:** Nine readers had been guarded one at a time against rows the boundary now stops. The guards are gone, and so is the filter the system-event readers carried.

## Fixed

**Three Damaged-Row Shapes No Longer Stop Setup:** A non-dict incident row, a non-dict to-do row, and a silence episode with a text timestamp each stopped setup.

**A Device Returning After Set-Aside Is A Fresh Problem:** A row a person had deleted was recorded as re-added when its device returned after being set aside.
