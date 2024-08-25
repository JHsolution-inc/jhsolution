import time, pytest

from jhsolution import utils

@pytest.mark.dependency(name='test_signer', scope='session')
def test_signer() -> None:
	signer1 = utils.TokenSigner('test1', 0)
	signer2 = utils.TokenSigner('test2', 0)

	data1 = {'some': 'object'}
	data2 = {'another': 'object'}

	token1 = signer1.sign(data1)
	assert data1 == signer1.unsign(token1)
	assert signer2.unsign(token1) is None

	token2 = signer2.sign(data2)
	assert data2 == signer2.unsign(token2)
	assert signer1.unsign(token2) is None

	time.sleep(1)

	assert signer1.unsign(token1) is None
	assert signer2.unsign(token2) is None
