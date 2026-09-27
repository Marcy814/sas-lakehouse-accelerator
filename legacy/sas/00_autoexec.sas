/*------------------------------------------------------------------------------
  Programme : 00_autoexec.sas
  Système   : Entrepôt actuariel (SAS 9.4 M7, serveur AIX)
  Objet     : Bibliothèques et paramètres communs du traitement de nuit
------------------------------------------------------------------------------*/
options mprint mlogic symbolgen compress=yes;

libname src  "/sasdata/policyadmin/extract" access=readonly;
libname dwh  "/sasdata/dwh/actuariat";

%let date_ref = '30JUN2026'd;
%let annee_debut = 2023;
%let annee_fin   = 2025;
