# Publishing rules

Rules to keep when the add-in is shared (GitHub, a release zip, or the Autodesk App Store). They come from a reading
of Autodesk's public terms (General Terms of Use, Autodesk Platform Services Terms, Acceptable Use Policy, Fusion
licence pages). This is not legal advice. Read the App Store Publisher Agreement in full before any App Store
submission, and ask Autodesk when a point is unclear.

## Rules

1. **Own name.** The add-in, its folder, its release zip and its repository name carry no "Fusion" or "Autodesk".
   Describe it as "for Autodesk Fusion" or "works with Autodesk Fusion". Never "powered by Autodesk".
2. **No Autodesk logos or icons.** The add-in and its pages use only Paramability art. Add this footnote where the
   add-in is presented: "Autodesk and Fusion are trademarks of Autodesk, Inc. Paramability is not affiliated with
   Autodesk."
3. **Documented API only.** No reading of `.f3d` internals, no patching of Fusion, and nothing that works around
   licence limits (for example no export format that the user's licence does not offer, and no fallback that tries
   to unlock one).
4. **Leave the design as it was.** Change parameters only in the open design and always restore them; do not create
   extra documents per test shape (Personal allows a limited number of active documents).
5. **Own code.** Do not copy Autodesk sample code unless Autodesk marks it as free to redistribute.
6. **Licence and user note.** Ship under an open source licence with an "as is" disclaimer. The README tells users
   that their own Fusion licence still applies: Personal is for non-commercial use, Education is for learning only.
7. **Positioning.** Paramability is a print preparation and configurator tool. Do not present the add-in or the app
   as a replacement for modelling in Fusion.
8. **Development licence.** Development and testing on a Personal licence stays non-commercial. If Paramability
   earns money, develop on a paid licence or an Autodesk developer programme licence.

## Open points

- Using the API beyond internal use falls under the Autodesk Platform Services Terms, which forbid "competitive"
  products and let Autodesk decide what that means. A print preparation and configurator tool looks low risk, but
  no clause says so. Ask Autodesk before an App Store listing.
- The App Store Publisher Agreement was not read yet.
