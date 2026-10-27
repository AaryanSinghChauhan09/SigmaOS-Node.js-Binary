    # SigmaOS-Node.js-Binary

    Node.js binary distribution manager

    Part of the **SigmaOS** sovereign operating-system ecosystem — a multi-repository
    distribution modelled on Linux Mint and Omarchy Linux. See the parent
    [`SigmaOS`](https://github.com/AaryanSinghChauhan09/SigmaOS) repository for the
    full component index.

    ## Upstream inspirations
    - https://github.com/linuxmint/distributions

    ## Design principles applied
    - **Separation of Concerns**
- **Defensive Programming**
- **Fail-Fast**
- **DRY**
- **KISS**
- **Deterministic Testing**

    ## Usage
    Verbs: `list, install-plan, use, mirror-plan`

    ```
    $ sigma-node list --manifest index.json --lts
v22.11.0  lts=Jam   date=2024-11-20  npm=10.9.0
$ sigma-node install-plan v22.11.0 --arch x64 --mirror https://nodejs.org/dist
$ sigma-node use v22.11.0 --prefix ~/.local/share/sigma-node --shell fish
$ sigma-node mirror-plan https://npm.elemecdn.com --tool npm

    ```

    ## Build & test
    ```
    make build
    make test
    ```

    ## Licence
    GNU General Public License v3.0 (FOSS).
