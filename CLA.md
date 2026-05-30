# flinttrade contributor licence agreement

By submitting a pull request, issue patch, or any other contribution to the
flinttrade project ("the Project"), you ("the Contributor") agree to the
following terms:

1. **Grant of licence.** You licence your contribution to the Project and to
   recipients of software distributed by the Project under the terms of the
   GNU Affero General Public License version 3 or (at your option) any later
   version ("AGPL-3.0-or-later"). You retain copyright in your contribution.

2. **Original work.** You confirm that your contribution is your original work,
   or that you have the right to submit it under AGPL-3.0-or-later (for
   example, you authored it during personal time and your employer asserts no
   claim, or your employer has explicitly authorised the contribution).

3. **No warranty.** Your contribution is provided "as is" without warranty of
   any kind.

4. **Patents.** You grant the Project and recipients a perpetual, worldwide,
   non-exclusive, no-charge, royalty-free, irrevocable patent licence to make,
   have made, use, offer to sell, sell, import, and otherwise transfer your
   contribution, where such licence applies only to those patent claims
   licensable by you that are necessarily infringed by your contribution.

5. **Acknowledgement.** By opening a pull request, you acknowledge that you
   have read and agree to these terms.

The Project maintainer (Navaneesh V N) accepts contributions under AGPL-3.0-or-later
in line with this CLA. The maintainer's own contributions are governed by the
same terms as the Contributor's, applied to themself.

If you are submitting on behalf of an organisation, please confirm that you
have authority to bind the organisation to this CLA.

---

## How to sign (GPG fingerprint binding — Identity H8)

A GitHub username plus an "I agree" comment is too easy to spoof. To make the
contribution chain cryptographically attributable, flinttrade binds your CLA
signature to a **GPG fingerprint** and CI verifies that every commit on your PR is
signed with that same key.

First-time contributor flow:

1. Publish your GPG public key (e.g. `gpg --send-keys <fingerprint>` to a keyserver,
   or attach the ASCII-armoured key to your first PR).
2. Sign the text of this `CLA.md` with that key:
   `gpg --armor --detach-sign --output cla.sig CLA.md`
3. Open your pull request and comment **"I agree to the CLA"**, attaching the
   detached signature (`cla.sig`, base64-encoded) and your key fingerprint.
4. The maintainer reviews and ratifies the first signature, then adds your record
   to `.github/cla-config.yml` in a separate commit. Subsequent PRs are verified
   automatically by `scripts/check-cla-gpg-binding.py`.

Configure your local git to sign commits:

```
git config user.signingkey <your-fingerprint>
git config commit.gpgsign true
```
