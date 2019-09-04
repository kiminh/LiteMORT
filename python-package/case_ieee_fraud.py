#https://www.kaggle.com/kyakovlev/ieee-cv-options
#https://www.kaggle.com/kyakovlev/ieee-experimental

# General imports
import numpy as np
import pandas as pd
import os, sys, gc, warnings, random, datetime

from sklearn import metrics
from sklearn.preprocessing import LabelEncoder
from sklearn.model_selection import KFold, TimeSeriesSplit
from tqdm import tqdm
import lightgbm as lgb
import pickle
import time
from litemort import *

import math
warnings.filterwarnings('ignore')
def seed_everything(seed=0):
    random.seed(seed)
    np.random.seed(seed)

isTimeSeires = True
isMORT = len(sys.argv)>1 and sys.argv[1] == "mort"
#isMORT = True
SEED = 42
verbose_eval=200
seed_everything(SEED)
TARGET = 'isFraud'
START_DATE = datetime.datetime.strptime('2017-11-30', '%Y-%m-%d')
NFOLDS_0=20
NFOLDS = 0 if isTimeSeires else 5
#some_rows = 10000
some_rows = None
data_root = 'E:/Kaggle/ieee_fraud/input/'
pkl_path = f'{data_root}/_yak_{some_rows}.pickle'

def make_predictions(tr_df, tt_df, features_columns, target, lgb_params):
    print(f'train_df={tr_df.shape} test_df={tt_df.shape} \nlgb_params={lgb_params}')
    if isTimeSeires:
        folds = TimeSeriesSplit(n_splits=NFOLDS_0)
    else:
        folds = KFold(n_splits=NFOLDS, shuffle=True, random_state=SEED)
    NFOLDS = 0
    X, y = tr_df[features_columns], tr_df[target]
    P, P_y = tt_df[features_columns], tt_df[target]
    tt_df = tt_df[['TransactionID', target]]
    predictions = np.zeros(len(tt_df))
    fold_score_sum=0
    for fold_, (trn_idx, val_idx) in enumerate(folds.split(X, y)):
        if fold_<15:
            continue
        NFOLDS = NFOLDS+1
        t0 = time.time()
        print('Fold:', fold_)
        tr_x, tr_y = X.iloc[trn_idx, :], y[trn_idx]
        vl_x, vl_y = X.iloc[val_idx, :], y[val_idx]
        print(len(tr_x), len(vl_x))
        if isMORT:
            model = LiteMORT(lgb_params).fit(tr_x, tr_y, eval_set=[(vl_x, vl_y)])
            best_iter = 1000
            #pred_val = model.predict(vl_x)
            pred_raw = model.predict_raw(vl_x)
            #y_pred[val_idx] = pred_raw
            fold_score = metrics.roc_auc_score(vl_y, pred_raw)
            if isTimeSeires:
                pass
            else:
                pp_p = model.predict_raw(P)
        else:
            tr_data = lgb.Dataset(tr_x, label=tr_y)
            vl_data = lgb.Dataset(vl_x, label=vl_y)
            estimator = lgb.train(lgb_params,tr_data,valid_sets=[tr_data, vl_data],verbose_eval=verbose_eval, )
            best_iter = estimator.best_iteration
            if isTimeSeires:
                pass
            else:
                pp_p = estimator.predict(P)
            pred_raw = estimator.predict(vl_x)
            fold_score = metrics.roc_auc_score(vl_y, pred_raw)
            del tr_data, vl_data
        if isTimeSeires:
            pass
        else:
            predictions += pp_p
        fold_score_sum += fold_score

        if False:
            feature_imp = pd.DataFrame(sorted(zip(estimator.feature_importance(), X.columns)),columns=['Value', 'Feature'])
            print(feature_imp)

        print(f'Fold:{fold_} score={fold_score} time={time.time()-t0:.4g} tr_x={tr_x.shape} val_x={vl_x.shape}'  )
        del tr_x, tr_y, vl_x, vl_y
        gc.collect()
        #break

    if verbose_eval == 1:
        input("Press Enter to pass this debug model...")
        os._exit(-1)

    if isTimeSeires:
        print(f'====== Final model for TimeSeires: best_iter={best_iter} X={X.shape} y={y.shape} ')
        del lgb_params['early_stopping_rounds']
        if isMORT:
            lgb_params['n_estimators'] = (int)(best_iter)
            model = LiteMORT(lgb_params).fit(X, y)
            tt_df['prediction'] = model.predict_raw(P)
        else:
            clf = lgb.LGBMClassifier(**lgb_params, num_boost_round=best_iter)
            clf.fit(X, y)
            tt_df['prediction'] = clf.predict_proba(P)[:, 1]
    else:
        tt_df['prediction'] = predictions/ NFOLDS

    return tt_df,fold_score_sum/NFOLDS

def M_PickSamples(pick_samples,df_train,df_test):
    nMost = min(df_train.shape[0], df_test.shape[0])
    random.seed(42)
    subset = random.sample(range(nMost), pick_samples)
    df_train = df_train.iloc[subset, :].reset_index(drop=True)
    df_test = df_test.iloc[subset, :].reset_index(drop=True)
    print('====== Mort_PickSamples ... df_train={} df_test={}'.format(df_train.shape, df_test.shape))
    return df_train,df_test

if os.path.isfile(pkl_path):
    print("====== Load pickle @{} ......".format(pkl_path))
    with open(pkl_path, "rb") as fp:
        [train_df, test_df, features_columns, TARGET] = pickle.load(fp)
else:
    print('Load Data')
    train_df = pd.read_pickle(f'{data_root}/yak/train_transaction.pkl')
    test_df = pd.read_pickle(f'{data_root}/yak/test_transaction.pkl')
    train_identity = pd.read_pickle(f'{data_root}/yak/train_identity.pkl')
    test_identity = pd.read_pickle(f'{data_root}/yak/test_identity.pkl')

    base_columns = list(train_df) + list(train_identity)
    print('Shape control:', train_df.shape, test_df.shape)

    ########################### Reset values for "noise" card1
    i_cols = ['card1']

    for col in i_cols:
        valid_card = pd.concat([train_df[[col]], test_df[[col]]])
        valid_card = valid_card[col].value_counts()
        valid_card = valid_card[valid_card>2]
        valid_card = list(valid_card.index)

        train_df[col] = np.where(train_df[col].isin(valid_card), train_df[col], np.nan)
        test_df[col]  = np.where(test_df[col].isin(valid_card), test_df[col], np.nan)

    ########################### Freq encoding
    i_cols = ['card1','card2','card3','card5',
              'C1','C2','C3','C4','C5','C6','C7','C8','C9','C10','C11','C12','C13','C14',
              'D1','D2','D3','D4','D5','D6','D7','D8','D9',
              'addr1','addr2',
              'dist1','dist2',
             ]

    for col in i_cols:
        temp_df = pd.concat([train_df[[col]], test_df[[col]]])
        valid_card = temp_df[col].value_counts().to_dict()
        train_df[col+'_fq_enc'] = train_df[col].map(valid_card)
        test_df[col+'_fq_enc']  = test_df[col].map(valid_card)

    ########################### ProductCD and M4 Target mean
    for col in ['ProductCD','M4']:
        temp_dict = train_df.groupby([col])[TARGET].agg(['mean']).reset_index().rename(
                                                            columns={'mean': col+'_target_mean'})
        temp_dict.index = temp_dict[col].values
        temp_dict = temp_dict[col+'_target_mean'].to_dict()

        train_df[col+'_target_mean'] = train_df[col].map(temp_dict)
        test_df[col+'_target_mean']  = test_df[col].map(temp_dict)

    ########################### M columns (except M4)
    # All these columns are binary encoded 1/0
    # We can have some features from it
    i_cols = ['M1','M2','M3','M5','M6','M7','M8','M9']

    for df in [train_df, test_df]:
        df['M_sum'] = df[i_cols].sum(axis=1).astype(np.int8)
        df['M_na'] = df[i_cols].isna().sum(axis=1).astype(np.int8)

    ########################### TransactionAmt

    # Let's add some kind of client uID based on cardID ad addr columns
    # The value will be very specific for each client so we need to remove it
    # from final feature. But we can use it for aggregations.
    train_df['uid'] = train_df['card1'].astype(str) + '_' + train_df['card2'].astype(str)
    test_df['uid'] = test_df['card1'].astype(str) + '_' + test_df['card2'].astype(str)

    train_df['uid2'] = train_df['uid'].astype(str) + '_' + train_df['card3'].astype(str) + '_' + train_df['card5'].astype(
        str)
    test_df['uid2'] = test_df['uid'].astype(str) + '_' + test_df['card3'].astype(str) + '_' + test_df['card5'].astype(str)

    train_df['uid3'] = train_df['uid2'].astype(str) + '_' + train_df['addr1'].astype(str) + '_' + train_df['addr2'].astype(
        str)
    test_df['uid3'] = test_df['uid2'].astype(str) + '_' + test_df['addr1'].astype(str) + '_' + test_df['addr2'].astype(str)

    # Check if the Transaction Amount is common or not (we can use freq encoding here)
    # In our dialog with a model we are telling to trust or not to these values
    train_df['TransactionAmt_check'] = np.where(train_df['TransactionAmt'].isin(test_df['TransactionAmt']), 1, 0)
    test_df['TransactionAmt_check'] = np.where(test_df['TransactionAmt'].isin(train_df['TransactionAmt']), 1, 0)

    # For our model current TransactionAmt is a noise
    # https://www.kaggle.com/kyakovlev/ieee-check-noise
    # (even if features importances are telling contrariwise)
    # There are many unique values and model doesn't generalize well
    # Lets do some aggregations
    i_cols = ['card1', 'card2', 'card3', 'card5', 'uid', 'uid2', 'uid3']

    for col in i_cols:
        for agg_type in ['mean', 'std']:
            new_col_name = col + '_TransactionAmt_' + agg_type
            temp_df = pd.concat([train_df[[col, 'TransactionAmt']], test_df[[col, 'TransactionAmt']]])
            # temp_df['TransactionAmt'] = temp_df['TransactionAmt'].astype(int)
            temp_df = temp_df.groupby([col])['TransactionAmt'].agg([agg_type]).reset_index().rename(
                columns={agg_type: new_col_name})

            temp_df.index = list(temp_df[col])
            temp_df = temp_df[new_col_name].to_dict()

            train_df[new_col_name] = train_df[col].map(temp_df)
            test_df[new_col_name] = test_df[col].map(temp_df)

    for col in list(train_df):
        if train_df[col].dtype == 'O':
            print(col)
            train_df[col] = train_df[col].fillna('unseen_before_label')
            test_df[col] = test_df[col].fillna('unseen_before_label')

            train_df[col] = train_df[col].astype(str)
            test_df[col] = test_df[col].astype(str)

            le = LabelEncoder()
            le.fit(list(train_df[col]) + list(test_df[col]))
            train_df[col] = le.transform(train_df[col])
            test_df[col] = le.transform(test_df[col])

            train_df[col] = train_df[col].astype('category')
            test_df[col] = test_df[col].astype('category')

    rm_cols = [
        'TransactionID','TransactionDT', # These columns are pure noise right now
        TARGET,                          # Not target in features))
        'uid','uid2','uid3',             # Our new client uID -> very noisy data
    ]
    features_columns = [col for col in list(train_df) if col not in rm_cols]
    if some_rows is not None:
        train_df,test_df = M_PickSamples(some_rows,train_df,test_df)

    if isTimeSeires:
        train_df = train_df.sort_values('TransactionDT')
        test_df = test_df.sort_values('TransactionDT')
    with open(pkl_path, "wb") as fp:  # Pickling
        pickle.dump([train_df, test_df, features_columns, TARGET], fp)


lgb_params = { 'objective':'binary',
                    'boosting_type':'gbdt',
                    'metric':'auc',
                    'min_data_in_leaf': 64,
                    'salp_bins':0,
                   'elitism':16,
                    'n_jobs':-1,
                    'learning_rate':0.01,      #0.005
                    'num_leaves': 2**8,
                    'max_depth':-1,
                    'tree_learner':'serial',
                    'colsample_bytree': 0.7,
                    'subsample_freq':1,
                    'subsample':0.7,
                    'n_estimators':800,
                    #'max_bin':255,
                    'verbose':1,
                    'verbose_eval':verbose_eval,
                    'seed': SEED,
                    'early_stopping_rounds':100,
                }
lgb_params['n_estimators'] = 20000
lgb_params['early_stopping_rounds'] = 100
test_predictions,fold_score = make_predictions(train_df, test_df, features_columns, TARGET, lgb_params)

#input("Press Enter to submit...")
model='MORT' if isMORT else 'LGB'
test_predictions['isFraud'] = test_predictions['prediction']
#test_predictions[['TransactionID', 'isFraud']].to_csv(f'submit_{some_rows}_{0.5}.csv', index=False,compression='gzip')
path = f'E:/Kaggle/ieee_fraud/result/[{model}]_{some_rows}_{fold_score:.5f}_F{NFOLDS}.csv'
test_predictions[['TransactionID', 'isFraud']].to_csv(path, index=False)        #,compression='gzip'
print(f"test_predictions[['TransactionID', 'isFraud']] to_csv @{path}")
input("Press Enter to exit...")
'''
    0.9380  lr=0.1          leaves=32
    0.9444
    0.9468  lr=0.005        leaves=256
'''