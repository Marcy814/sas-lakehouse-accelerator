/*------------------------------------------------------------------------------
  Programme : 03_ratio_sinistralite.sas
  Objet     : Ratio de sinistralité annuel par produit (primes acquises au prorata)
  Entrées   : dwh.polices_courantes, dwh.sinistres_enrichis
  Sorties   : dwh.ratio_sinistralite
------------------------------------------------------------------------------*/
%include "/sasprog/actuariat/00_autoexec.sas";

%macro primes_acquises(annee);
  proc sql;
    create table work.primes_&annee as
    select produit,
           &annee as annee,
           sum(prime_annuelle
               * (min(date_fin, mdy(12, 31, &annee)) - max(date_debut, mdy(1, 1, &annee)) + 1)
               / 365) as primes_acquises
    from dwh.polices_courantes
    where date_debut <= mdy(12, 31, &annee)
      and date_fin   >= mdy(1, 1, &annee)
    group by produit;
  quit;
%mend primes_acquises;

%macro boucle_annees;
  %do a = &annee_debut %to &annee_fin;
    %primes_acquises(&a);
  %end;
  data work.primes;
    set %do a = &annee_debut %to &annee_fin; work.primes_&a %end;;
  run;
%mend boucle_annees;

%boucle_annees;

proc summary data=dwh.sinistres_enrichis nway;
  class produit annee_sinistre;
  var montant_reclame montant_paye;
  output out=work.sinistres_agg(drop=_type_ rename=(_freq_=nb_sinistres annee_sinistre=annee))
         sum(montant_reclame)=total_reclame
         sum(montant_paye)=total_paye;
run;

proc sort data=work.primes;         by produit annee; run;
proc sort data=work.sinistres_agg;  by produit annee; run;

data dwh.ratio_sinistralite;
  merge work.primes(in=a) work.sinistres_agg(in=b);
  by produit annee;
  if a;
  if not b then do;
    nb_sinistres  = 0;
    total_reclame = 0;
    total_paye    = 0;
  end;
  ratio_sinistralite = total_paye / primes_acquises;
  format primes_acquises total_reclame total_paye comma15.2 ratio_sinistralite percent8.2;
run;
